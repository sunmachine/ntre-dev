#include "cbase.h"
#include "hud.h"
#include "hud_crosshair.h"
#include "iclientmode.h"
#include "view.h"
#include "vgui_controls/Controls.h"
#include "vgui/ISurface.h"
#include "c_playerresource.h"
#include "neo_crosshair.h"
#include "neo_gamerules.h"
#include "weapon_neobasecombatweapon.h"
#include "weapon_srs.h"

// memdbgon must be the last include file in a .cpp file!!!
#include "tier0/memdbgon.h"

using namespace vgui;

ConVar cl_neo_crosshair_scope_inaccuracy("cl_neo_crosshair_scope_inaccuracy", "1", FCVAR_ARCHIVE,
	"Show the player's inaccuracy when scoped", true, 0, true, 1);
ConVar cl_neo_crosshair_friendly_fire_warning("cl_neo_crosshair_friendly_fire_warning", "1", FCVAR_ARCHIVE,
	"Replace crosshair with friendly fire warning where applicable", true, 0, true, 1);

// NEO TODO (Rain): move to server game rules for server op toggling
ConVar cl_neo_scope_restrict_to_rectangle("cl_neo_scope_restrict_to_rectangle", "1", FCVAR_CHEAT,
	"Whether to enforce rectangular sniper scope shape regardless of screen ratio.", true, 0.0, true, 1.0);

// NEO's crosshair and scope drawing. CHudCrosshair::Paint in the SDK file
// calls this under #ifdef NEO and keeps Valve's own body under #else.
void CHudCrosshair::PaintNeo()
{
	if (!m_pCrosshair)
		return;

	if (!IsCurrentViewAccessAllowed())
		return;

	if (!ShouldDraw())
		return;

	float x, y;
	bool bBehindCamera;
	GetDrawPosition(&x, &y, &bBehindCamera, m_vecCrossHairOffsetAngle);

	if (bBehindCamera)
		return;

	float flWeaponScale_X = 1.0f;
	float flWeaponScale_Y = 1.0f;
	int iTextureW = m_pCrosshair->Width();
	int iTextureH = m_pCrosshair->Height();

	// DevMsg("TexFileW: %s (%s) :: W %d H %d\n", m_pCrosshair->szTextureFile, m_pCrosshair->szShortName, iTextureW,
	// iTextureH);

	if (iTextureH == 0 || iTextureW == 0)
	{
		Assert(false);
		return;
	}

	C_NEO_Player *pPlayer = C_NEO_Player::GetLocalNEOPlayer();
	if (!pPlayer)
		return;

	if (pPlayer->IsObserver())
	{
		pPlayer = ToNEOPlayer(ClientEntityList().GetBaseEntity(GetSpectatorTarget()));
		if (!pPlayer)
			return;
	}
	auto *pWeapon = static_cast<CNEOBaseCombatWeapon *>(pPlayer->GetActiveWeapon());
	if (pWeapon)
	{
		// NEO HACK (Rain): this should get implemented in virtual pNeoWep->GetWeaponCrosshairScale
		if (pWeapon && pWeapon->GetNeoWepBits() & NEO_WEP_SCOPEDWEAPON)
		{
			int screenWidth, screenHeight;
			GetHudSize(screenWidth, screenHeight);
			Assert(screenWidth > 0 && screenHeight > 0);

			// Scale scope size based on resolution.
			flWeaponScale_X = static_cast<float>(screenWidth) / iTextureW;
			flWeaponScale_Y = static_cast<float>(screenHeight) / iTextureH;

			if (cl_neo_scope_restrict_to_rectangle.GetBool())
			{
// This is how many see-through "lens" pixels there are in X vs Y axes of the default scope03 texture.
#define RECT_SCOPE03_VISIBLE_AREA_SCALING (720.0f / 960.0f)
				// Get the smaller dimension as base for the square scope.
				flWeaponScale_X = Min(flWeaponScale_X, flWeaponScale_Y);
				// And further downscale with this ratio to make the actual scope lens part of the texture square
				// shaped.
				flWeaponScale_Y = flWeaponScale_X * RECT_SCOPE03_VISIBLE_AREA_SCALING;
				// We can increase the final rectangle scale size by about this much without overflowing the screen
				// area.
				flWeaponScale_X *= (1.0f + (1.0f - RECT_SCOPE03_VISIBLE_AREA_SCALING));
				flWeaponScale_Y *= (1.0f + (1.0f - RECT_SCOPE03_VISIBLE_AREA_SCALING));
			}
		}
		else
		{
			pWeapon->GetWeaponCrosshairScale(flWeaponScale_X);
			flWeaponScale_Y = flWeaponScale_X;
		}
	}

	float flWidth = flWeaponScale_X * (float)iTextureW;
	float flHeight = flWeaponScale_Y * (float)iTextureH;

	int iWidth = (int)(flWidth + 0.5f);
	int iHeight = (int)(flHeight + 0.5f);

	int iX = (int)(x + 0.5f);
	int iY = (int)(y + 0.5f);

	// NEO TODO (nullsystem): Probably be better if the entire class refreshed to our own
	// thing and can do away with that CHudTexture nonsense entirely
	const bool bIsScopedWep = pWeapon && pWeapon->GetNeoWepBits() & NEO_WEP_SCOPEDWEAPON;

	bool bThisFrameRefreshCrosshair = m_bRefreshCrosshair;
	auto *pNeoPlayer = static_cast<C_NEO_Player *>(pPlayer);
	bool bTakeSpecCrosshair = false;
	const char *pszNeoCrosshair = cl_neo_crosshair.GetString();
	if (cl_neo_crosshair_network.GetBool() && IsLocalPlayerSpectator())
	{
		const int iPlayerIdx = pNeoPlayer->entindex();
		const bool bPlayerIdxValid = ((iPlayerIdx >= 0) && (iPlayerIdx < MAX_PLAYERS));
		Assert(bPlayerIdxValid);
		if (bPlayerIdxValid)
		{
			if (m_iPrevPlayerIdx != iPlayerIdx)
			{
				m_flLastCheckedXHair = 0.0f;
				m_iPrevPlayerIdx = iPlayerIdx;
			}
			bTakeSpecCrosshair = true;
			bThisFrameRefreshCrosshair = false;
			pszNeoCrosshair = g_PR->GetNeoCrosshair(iPlayerIdx);

			// NEO NOTE (nullsystem): Only check the string per second
			static constexpr float FL_XHAIR_REFRESH_INTERVAL = 1.0f;
			if (m_flLastCheckedXHair + FL_XHAIR_REFRESH_INTERVAL < gpGlobals->curtime)
			{
				m_flLastCheckedXHair = gpGlobals->curtime;
				bThisFrameRefreshCrosshair = (V_strcmp(m_szLocalStrPlayerCrosshair, pszNeoCrosshair) != 0);
			}
		}
	}
	else if (m_iPrevPlayerIdx != pNeoPlayer->entindex())
	{
		bThisFrameRefreshCrosshair = true;
		m_iPrevPlayerIdx = pNeoPlayer->entindex();
	}

	if (bThisFrameRefreshCrosshair)
	{
		V_strcpy_safe(m_szLocalStrPlayerCrosshair, pszNeoCrosshair);
		const bool bImported = ImportCrosshair(&m_crosshairInfo, pszNeoCrosshair);
		if (!bImported)
		{
			// NEO NOTE (nullsystem): Don't revert, just enforce default if it
			// is not given properly
			ResetCrosshairToDefault(&m_crosshairInfo);
		}
		if (!bTakeSpecCrosshair)
		{
			m_bRefreshCrosshair = false;
		}
	}

	bool bHideCrosshair = (NEORules() && NEORules()->GetHiddenHudElements() & NEO_HUD_ELEMENT_CROSSHAIR);

	ENeoCrosshairWep eNeoXHairWep = CROSSHAIR_WEP_DEFAULT;
	if (pWeapon)
	{
		int iNeoXHairWep = MAP_WEAPON_TYPE_TO_XHAIR[NEO_WEAPON_TYPE[pWeapon->WeaponIndex()]];
		if (iNeoXHairWep >= CROSSHAIR_WEP_DEFAULT && iNeoXHairWep < CROSSHAIR_WEP_DEFAULT_HIPFIRE &&
			false == pNeoPlayer->m_bInAim)
		{
			iNeoXHairWep += CROSSHAIR_WEP_DEFAULT_HIPFIRE;
		}
		eNeoXHairWep =
			static_cast<ENeoCrosshairWep>(UseCrosshairIndexFor(&m_crosshairInfo, iNeoXHairWep, &bHideCrosshair));
	}
	CrosshairWepInfo *crh = &m_crosshairInfo.wep[eNeoXHairWep];
	const int iTexXHId = m_iTexXHId[clamp(crh->iStyle, 0, CROSSHAIR_STYLE__TOTAL - 1)];

	bool showFriendlyFireCrosshair = false;
	if (NEORules()->GetGameType() != NEO_GAME_TYPE_DM && cl_neo_crosshair_friendly_fire_warning.GetBool())
	{
		trace_t iffTrace;
		CTraceFilterSimpleList iffTraceFilter(COLLISION_GROUP_NONE);
		iffTraceFilter.AddEntityToIgnore(pPlayer);
		constexpr int IFF_TRACELINE_LENGTH = 8192; // a little over 200m
		UTIL_TraceLine(pPlayer->Weapon_ShootPosition(),
			pPlayer->Weapon_ShootPosition() + pPlayer->GetAutoaimVector(0) * IFF_TRACELINE_LENGTH, MASK_SHOT_HULL,
			&iffTraceFilter, &iffTrace);
		showFriendlyFireCrosshair =
			IsPlayerIndex(iffTrace.GetEntityIndex()) && iffTrace.m_pEnt->GetTeamNumber() == pPlayer->GetTeamNumber();
	}

	if (bIsScopedWep && pPlayer->m_bInAim)
	{
		m_pCrosshair->DrawSelfCropped(
			iX - (iWidth / 2), iY - (iHeight / 2), 0, 0, iTextureW, iTextureH, iWidth, iHeight, COLOR_WHITE);

		// NEO NOTE (Rain): If we "need" to bolt the gun, don't show the xhair inaccuracy.
		// This is a special case for SRS handling when un-scoping right after firing a bullet.
		// If we don't do this check, the player could see the scope inaccuracy effect for a
		// few frames after shooting, which can hinder the scope's visibility especially at long range
		// without offering any useful info to the player in return (i.e. the SRS post-fire
		// inaccuracy doesn't matter because they cannot shoot again anyway until it has decayed).
		bool weaponNeedsToBeBolted = false;
		if (pWeapon->GetNeoWepBits() & NEO_WEP_SRS)
		{
			weaponNeedsToBeBolted = assert_cast<CWeaponSRS *>(pWeapon)->GetNeedsBolting();
		}
		if (!weaponNeedsToBeBolted)
		{
			if (cl_neo_crosshair_scope_inaccuracy.GetBool())
			{
				const int size = pWeapon ? HalfInaccuracyConeInScreenPixels(pWeapon, m_iHalfScreenWidth) : 0;
				if (size)
				{
					surface()->DrawSetTexture(m_hCrosshairLight);
					surface()->DrawSetColor(COLOR_FADED_WHITE);
					surface()->DrawTexturedRect(x - size - m_iCrosshairLightWidth, y - size - m_iCrosshairLightHeight,
						x - size + m_iCrosshairLightWidth, y - size + m_iCrosshairLightHeight);
					surface()->DrawTexturedRect(x + size - m_iCrosshairLightWidth, y + size - m_iCrosshairLightHeight,
						x + size + m_iCrosshairLightWidth, y + size + m_iCrosshairLightHeight);
				}
			}
		}
	}
	else if (!bHideCrosshair)
	{
		if (showFriendlyFireCrosshair)
		{
			vgui::surface()->DrawSetTexture(m_iTexIFFId);
			int iTexWide, iTexTall;
			vgui::surface()->DrawGetTextureSize(m_iTexIFFId, iTexWide, iTexTall);
			iTexWide >>= 2;
			iTexTall >>= 2;
			vgui::surface()->DrawSetColor(COLOR_RED);
			vgui::surface()->DrawTexturedRect(iX - iTexWide, iY - iTexTall, iX + iTexWide, iY + iTexTall);
		}
		else if (iTexXHId > 0)
		{
			vgui::surface()->DrawSetTexture(iTexXHId);
			int iTexWide, iTexTall;
			vgui::surface()->DrawGetTextureSize(iTexXHId, iTexWide, iTexTall);
			iTexWide >>= 1;
			iTexTall >>= 1;
			vgui::surface()->DrawSetColor(crh->color);
			vgui::surface()->DrawTexturedRect(iX - iTexWide, iY - iTexTall, iX + iTexWide, iY + iTexTall);
		}
		else
		{
			PaintCrosshair(crh, HalfInaccuracyConeInScreenPixels(pWeapon, m_iHalfScreenWidth), iX, iY);
		}
	}

	if (bIsScopedWep && pPlayer->m_bInAim)
	{
		int screenWidth, screenHeight;
		GetHudSize(screenWidth, screenHeight);

		const unsigned int prevCornerFlags = GetRoundedCorners();
		SetRoundedCorners(0);

		// NEO TODO (Rain): the NT scope does a color slide around RGB 0-20,
		// instead of being completely black. For now, just picking a close-ish color
		// instead of accurately representing. Should probably pick samples of the
		// scope texture around the edges, and use those for fill color, instead.
		// Stretching the scope wouldn't be a great workaround, because it ties the scope
		// FOV to screen resolution, which can give an unfair advantage on widescreen
		// or multi-monitor setups.
		const Color blockColor = Color(16, 17, 16, 255);

		// Draw black box on left side of the scope.
		DrawBox(0, 0, iX - (iWidth / 2), screenHeight, blockColor, 1.0f);
		// Draw black box on right side of the scope.
		DrawBox((iX - (iWidth / 2) + iWidth), 0, screenWidth, screenHeight, blockColor, 1.0f);
		// Draw black box on top of the scope.
		DrawBox(iX - (iWidth / 2), 0, iWidth, iY - (iHeight / 2), blockColor, 1.0f);
		// Draw black box under the scope.
		DrawBox(iX - (iWidth / 2), screenHeight - (iY - (iHeight / 2)), iWidth, screenHeight, blockColor, 1.0f);

		// Reset corner rounding.
		SetRoundedCorners(prevCornerFlags);
	}
}
