#ifndef NEO_CASEFIX_H
#define NEO_CASEFIX_H
#ifdef _WIN32
#pragma once
#endif

class IFileSystem;

#ifdef LINUX
// Mirrors the other search paths' mixed-case directories and font files as lowercase symlinks
// under the mod's casefix/ directory, which gameinfo.txt lists ahead of them.
void FixupMixedCasePaths(IFileSystem *filesystem);
#endif

#endif // NEO_CASEFIX_H
