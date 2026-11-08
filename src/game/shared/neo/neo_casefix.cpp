#include "cbase.h"
#include "neo_casefix.h"
#ifdef LINUX

#include <dirent.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

#include "filesystem.h"
#include "tier1/strtools.h"
#include "tier1/utlvector.h"

// memdbgon must be the last include file in a .cpp file!!!
#include "tier0/memdbgon.h"

// NEO HACK (sunmachine): Since the TF2 SDK and 64-bit update, the engine on Linux lowercases every
// path it is asked for, then matches file names ignoring case but directory names exactly, and finds
// a custom font only under its lowercase file name. OG:NT ships sound/weapons/Jitte/, NEUROPOL2.ttf,
// X-SCALE_.TTF, Cstrike.ttf and AFL.ttf, so the Jitte sounds and those font families failed unless the
// player renamed them by hand. Those files live in another Steam app's folder, so instead every
// mixed-case directory and font file in the other search paths is mirrored as a lowercase symlink
// under casefix/, which gameinfo.txt lists ahead of them. A mixed-case directory is linked whole,
// since the engine resolves the file names inside it on its own.

static constexpr const char *CASEFIX_DIR = "casefix";
static constexpr int SEARCH_PATHS_BUFFER_LEN = 16384;

static bool HasUppercase(const char *name)
{
	for (; *name; ++name)
	{
		if (*name >= 'A' && *name <= 'Z')
		{
			return true;
		}
	}
	return false;
}

static bool IsFontFile(const char *name)
{
	const char *extension = V_GetFileExtension(name);
	return extension && (V_stricmp(extension, "ttf") == 0 || V_stricmp(extension, "otf") == 0);
}

static void JoinPath(const char *directory, const char *name, char (&out)[MAX_PATH])
{
	if (!directory[0])
	{
		V_strncpy(out, name, sizeof(out));
	}
	else
	{
		V_snprintf(out, sizeof(out), "%s/%s", directory, name);
	}
}

// Creates every directory on the way to the file at path.
static void MakeParentDirectories(const char *casefixRoot, char *path)
{
	for (char *p = path + V_strlen(casefixRoot) + 1; *p; ++p)
	{
		if (*p == '/')
		{
			*p = '\0';
			mkdir(path, 0755);
			*p = '/';
		}
	}
}

// Makes the lowercase form of relativePath under casefixRoot a symlink to target. A real file or
// directory already at that path belongs to the mod and is left alone.
static bool Mirror(const char *casefixRoot, const char *relativePath, const char *target)
{
	char lowercase[MAX_PATH];
	V_strncpy(lowercase, relativePath, sizeof(lowercase));
	V_strlower(lowercase);

	char linkPath[MAX_PATH];
	JoinPath(casefixRoot, lowercase, linkPath);
	MakeParentDirectories(casefixRoot, linkPath);

	char existing[MAX_PATH];
	const ssize_t existingLen = readlink(linkPath, existing, sizeof(existing) - 1);
	if (existingLen >= 0)
	{
		existing[existingLen] = '\0';
		if (V_strcmp(existing, target) == 0)
		{
			return true;
		}
		unlink(linkPath);
	}
	else
	{
		struct stat st;
		if (lstat(linkPath, &st) == 0)
		{
			return true;
		}
	}

	if (symlink(target, linkPath) != 0)
	{
		Warning("FixupMixedCasePaths: could not link %s: %s\n", linkPath, strerror(errno));
		return false;
	}
	return true;
}

// Walks one search path below relativeDir. A mixed-case directory is mirrored and not entered.
static void WalkDirectory(const char *casefixRoot, const char *searchPath, const char *relativeDir, int &linked)
{
	char fullDir[MAX_PATH];
	JoinPath(searchPath, relativeDir, fullDir);
	DIR *dir = opendir(fullDir);
	if (!dir)
	{
		return;
	}

	while (const dirent *entry = readdir(dir))
	{
		if (entry->d_name[0] == '.')
		{
			continue;
		}

		char relative[MAX_PATH];
		JoinPath(relativeDir, entry->d_name, relative);
		char full[MAX_PATH];
		JoinPath(searchPath, relative, full);

		struct stat st;
		if (lstat(full, &st) != 0 || S_ISLNK(st.st_mode))
		{
			continue;
		}

		if (S_ISDIR(st.st_mode))
		{
			if (HasUppercase(entry->d_name))
			{
				linked += Mirror(casefixRoot, relative, full) ? 1 : 0;
			}
			else
			{
				WalkDirectory(casefixRoot, searchPath, relative, linked);
			}
		}
		else if (HasUppercase(entry->d_name) && IsFontFile(entry->d_name))
		{
			linked += Mirror(casefixRoot, relative, full) ? 1 : 0;
		}
	}
	closedir(dir);
}

void FixupMixedCasePaths(IFileSystem *filesystem)
{
	// The mod directory is the only DEFAULT_WRITE_PATH.
	char modPath[MAX_PATH];
	filesystem->GetSearchPath_safe("DEFAULT_WRITE_PATH", false, modPath);
	if (char *separator = strchr(modPath, ';'))
	{
		*separator = '\0';
	}
	V_StripTrailingSlash(modPath);

	char casefixRoot[MAX_PATH];
	JoinPath(modPath, CASEFIX_DIR, casefixRoot);
	if (mkdir(casefixRoot, 0755) != 0 && errno != EEXIST)
	{
		Warning("FixupMixedCasePaths: could not create %s: %s\n", casefixRoot, strerror(errno));
		return;
	}

	char searchPaths[SEARCH_PATHS_BUFFER_LEN];
	filesystem->GetSearchPath_safe("GAME", false, searchPaths);
	CUtlStringList directories;
	V_SplitString(searchPaths, ";", directories);

	int linked = 0;
	for (const char *directory : directories)
	{
		char path[MAX_PATH];
		V_strncpy(path, directory, sizeof(path));
		V_StripTrailingSlash(path);
		if (V_strcmp(path, modPath) == 0 || V_strcmp(path, casefixRoot) == 0)
		{
			continue;
		}
		WalkDirectory(casefixRoot, path, "", linked);
	}
	DevMsg("FixupMixedCasePaths: %d mixed-case paths linked under %s\n", linked, casefixRoot);
}

#endif // LINUX
