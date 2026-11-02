//========= Copyright Valve Corporation, All rights reserved. ============//
//
// Purpose: 
//
// $NoKeywords: $
//=============================================================================//

#include "cbase.h"
#include "hud.h"
#include "hud_crosshair.h"
#include "iclientmode.h"
#include "view.h"
#include "vgui_controls/Controls.h"
#include "vgui/ISurface.h"
#include "ivrenderview.h"
#include "materialsystem/imaterialsystem.h"
#include "VGuiMatSurface/IMatSystemSurface.h"
#include "client_virtualreality.h"
#include "sourcevr/isourcevirtualreality.h"

#ifdef SIXENSE
#include "sixense/in_sixense.h"
#endif

#ifdef PORTAL
#include "c_portal_player.h"
#endif // PORTAL

#ifdef NEO
#include "weapon_neobasecombatweapon.h"
#include "weapon_srs.h"
#include "neo_gamerules.h"
#endif

// memdbgon must be the last include file in a .cpp file!!!
#include "tier0/memdbgon.h"

ConVar crosshair( "crosshair", "1", FCVAR_ARCHIVE );
ConVar cl_observercrosshair( "cl_observercrosshair", "1", FCVAR_ARCHIVE );

using namespace vgui;

int ScreenTransform( const Vector& point, Vector& screen );

#ifdef TF_CLIENT_DLL
// If running TF, we use CHudTFCrosshair instead (which is derived from CHudCrosshair)
#else
DECLARE_HUDELEMENT_DEPTH(CHudCrosshair, 9999); // NEO
#endif

#ifdef NEO
static inline bool g_bInstalledCVarCallback = false;

void CVGlobal_NeoClCrosshair(IConVar *var, [[maybe_unused]] const char *pOldString, [[maybe_unused]] float flOldValue)
{
	CHudCrosshair *crosshair = GET_HUDELEMENT(CHudCrosshair);
	if (crosshair && V_strstr(var->GetName(), "cl_neo_crosshair"))
	{
		// NEO NOTE (nullsystem): Mark for refresh
		crosshair->m_bRefreshCrosshair = true;
	}
}

#endif

CHudCrosshair::CHudCrosshair( const char *pElementName ) :
		CHudElement( pElementName ), BaseClass( NULL, "HudCrosshair" )
{
#ifdef NEO
	if (!g_bInstalledCVarCallback)
	{
		cvar->InstallGlobalChangeCallback(CVGlobal_NeoClCrosshair);
		g_bInstalledCVarCallback = true;
	}

	for (int i = 0; i < CROSSHAIR_STYLE__TOTAL; ++i)
	{
		if (CROSSHAIR_FILES[i][0])
		{
			m_iTexXHId[i] = vgui::surface()->CreateNewTextureID();
			vgui::surface()->DrawSetTextureFile(m_iTexXHId[i], CROSSHAIR_FILES[i], false, false);
		}
	}

	m_iTexIFFId = vgui::surface()->CreateNewTextureID();
	constexpr const char *IFF_TEXTURE_NAME = "vgui/hud/x1";
	vgui::surface()->DrawSetTextureFile(m_iTexIFFId, IFF_TEXTURE_NAME, false, false);

#endif

	vgui::Panel *pParent = g_pClientMode->GetViewport();
	SetParent( pParent );

	m_pCrosshair = 0;

	m_clrCrosshair = Color( 0, 0, 0, 0 );

	m_vecCrossHairOffsetAngle.Init();

#ifdef NEO
	m_hCrosshairLight = surface()->CreateNewTextureID();
	Assert(m_hCrosshairLight > 0);
	// NEO TODO (Adam) This is a copy of the original with everything but the center cross removed, perhaps move to ApplySchemeSettings and workout this name based off of the name of m_pCrosshair
	// in case of custom scopes (if we want to allow custom scopes I guess)
	surface()->DrawSetTextureFile(m_hCrosshairLight, "vgui/hud/scopes/scope03-1", 1, false);
	surface()->DrawGetTextureSize(m_hCrosshairLight, m_iCrosshairLightWidth, m_iCrosshairLightHeight);

	SetHiddenBits( HIDEHUD_PLAYERDEAD );
#else
	SetHiddenBits( HIDEHUD_PLAYERDEAD | HIDEHUD_CROSSHAIR );
#endif // NEO
}

CHudCrosshair::~CHudCrosshair()
{
#ifdef NEO
	cvar->RemoveGlobalChangeCallback(CVGlobal_NeoClCrosshair);
#endif
}

void CHudCrosshair::ApplySchemeSettings( IScheme *scheme )
{
	BaseClass::ApplySchemeSettings( scheme );

	m_pDefaultCrosshair = gHUD.GetIcon("crosshair_default");
	SetPaintBackgroundEnabled( false );

#ifdef NEO
	m_iHalfScreenWidth = ScreenWidth() * 0.5;
#endif // NEO
    SetSize( ScreenWidth(), ScreenHeight() );

	SetForceStereoRenderToFrameBuffer( true );
}

//-----------------------------------------------------------------------------
// Purpose: Save CPU cycles by letting the HUD system early cull
// costly traversal.  Called per frame, return true if thinking and 
// painting need to occur.
//-----------------------------------------------------------------------------
bool CHudCrosshair::ShouldDraw( void )
{
#ifdef NEO
	if (!m_pCrosshair)
		return false;

	if ( m_bHideCrosshair )
		return false;

	const auto* player = C_NEO_Player::GetLocalNEOPlayer();
	if (!player)
		return false;

	if (player->IsObserver())
	{
		switch (player->GetObserverMode())
		{
		case OBS_MODE_IN_EYE:
			player = ToNEOPlayer(player->GetObserverTarget());
			if (engine->IsHLTV() && player && player->IsObserver())
			{ // HLTV can spectate other spectators (and doesn't switch away from dead players by default)
				return false;
			}
			break;
			// NEO NOTE (Adam) technically cl_observercrosshair should allow us to see a crosshair when roaming, but we're early returning in the draw function anyway if we dont have a valid target so 
			// I removed the OBS_MODE_ROAMING clause here so stv demo watchers, who still have an observer target even when roaming, dont see a crosshair when normal spectators watching live dont.
			// NEO TODO Fix cl_observercrosshair for both
		default:
			return false;
		}
	}

	if (!player)
		return false;

	if (player->m_lifeState != LIFE_ALIVE)
		return false;

	if (player->GetFlags() & FL_FROZEN)
		return false;

	// This is the HL2 player logic from the ifndef NEO path below
	// that is commented out in the SDK code also.
	//if (player->m_HL2Local.m_bZooming)
	//	return false;

	if (player->IsInVGuiInputMode())
		return false;

	if (!crosshair.GetBool())
		return false;

	if (!CHudElement::ShouldDraw())
		return false;

	auto *wep = player->GetActiveWeapon();
	if (!wep || !wep->ShouldDrawCrosshair())
		return false;

	if (engine->IsDrawingLoadingImage())
		return false;

	if (engine->IsPaused())
		return false;

	if (!g_pClientMode->ShouldDrawCrosshair())
		return false;

	return true;

#else

	bool bNeedsDraw;

	if ( m_bHideCrosshair )
		return false;

	C_BasePlayer* pPlayer = C_BasePlayer::GetLocalPlayer();
	if ( !pPlayer )
		return false;

	C_BaseCombatWeapon *pWeapon = pPlayer->GetActiveWeapon();
	if ( pWeapon && !pWeapon->ShouldDrawCrosshair() )
		return false;

#ifdef PORTAL
	C_Portal_Player *portalPlayer = ToPortalPlayer(pPlayer);
	if ( portalPlayer && portalPlayer->IsSuppressingCrosshair() )
		return false;
#endif // PORTAL

	/* disabled to avoid assuming it's an HL2 player.
	// suppress crosshair in zoom.
	if ( pPlayer->m_HL2Local.m_bZooming )
		return false;
	*/

	// draw a crosshair only if alive or spectating in eye
	if ( IsX360() )
	{
		bNeedsDraw = m_pCrosshair && 
			!engine->IsDrawingLoadingImage() &&
			!engine->IsPaused() && 
			( !pPlayer->IsSuitEquipped() || g_pGameRules->IsMultiplayer() ) &&
			g_pClientMode->ShouldDrawCrosshair() &&
			!( pPlayer->GetFlags() & FL_FROZEN ) &&
			( pPlayer->entindex() == render->GetViewEntity() ) &&
			( pPlayer->IsAlive() ||	( pPlayer->GetObserverMode() == OBS_MODE_IN_EYE ) || ( cl_observercrosshair.GetBool() && pPlayer->GetObserverMode() == OBS_MODE_ROAMING ) );
	}
	else
	{
		bNeedsDraw = m_pCrosshair && 
			crosshair.GetInt() &&
			!engine->IsDrawingLoadingImage() &&
			!engine->IsPaused() && 
			g_pClientMode->ShouldDrawCrosshair() &&
			!( pPlayer->GetFlags() & FL_FROZEN ) &&
			( pPlayer->entindex() == render->GetViewEntity() ) &&
			!pPlayer->IsInVGuiInputMode() &&
			( pPlayer->IsAlive() ||	( pPlayer->GetObserverMode() == OBS_MODE_IN_EYE ) || ( cl_observercrosshair.GetBool() && pPlayer->GetObserverMode() == OBS_MODE_ROAMING ) );
	}

	return ( bNeedsDraw && CHudElement::ShouldDraw() );
#endif
}

#ifdef TF_CLIENT_DLL
extern ConVar cl_crosshair_red;
extern ConVar cl_crosshair_green;
extern ConVar cl_crosshair_blue;
extern ConVar cl_crosshair_scale;
#endif


void CHudCrosshair::GetDrawPosition ( float *pX, float *pY, bool *pbBehindCamera, QAngle angleCrosshairOffset )
{
	QAngle curViewAngles = CurrentViewAngles();
	Vector curViewOrigin = CurrentViewOrigin();

	int vx, vy, vw, vh;
	vgui::surface()->GetFullscreenViewport( vx, vy, vw, vh );

	float screenWidth = vw;
	float screenHeight = vh;

	float x = screenWidth / 2;
	float y = screenHeight / 2;

	bool bBehindCamera = false;

	C_BasePlayer* pPlayer = C_BasePlayer::GetLocalPlayer();
	if ( ( pPlayer != NULL ) && ( pPlayer->GetObserverMode()==OBS_MODE_NONE ) )
	{
		bool bUseOffset = false;
		
		Vector vecStart;
		Vector vecEnd;

		if ( UseVR() )
		{
			// These are the correct values to use, but they lag the high-speed view data...
			vecStart = pPlayer->Weapon_ShootPosition();
			Vector vecAimDirection = pPlayer->GetAutoaimVector( 1.0f );
			// ...so in some aim modes, they get zapped by something completely up-to-date.
			g_ClientVirtualReality.OverrideWeaponHudAimVectors ( &vecStart, &vecAimDirection );
			vecEnd = vecStart + vecAimDirection * MAX_TRACE_LENGTH;

			bUseOffset = true;
		}

#ifdef SIXENSE
		// TODO: actually test this Sixsense code interaction with things like HMDs & stereo.
        if ( g_pSixenseInput->IsEnabled() && !UseVR() )
		{
			// Never autoaim a predicted weapon (for now)
			vecStart = pPlayer->Weapon_ShootPosition();
			Vector aimVector;
			AngleVectors( CurrentViewAngles() - g_pSixenseInput->GetViewAngleOffset(), &aimVector );
			// calculate where the bullet would go so we can draw the cross appropriately
			vecEnd = vecStart + aimVector * MAX_TRACE_LENGTH;
			bUseOffset = true;
		}
#endif

		if ( bUseOffset )
		{
			trace_t tr;
			UTIL_TraceLine( vecStart, vecEnd, MASK_SHOT, pPlayer, COLLISION_GROUP_NONE, &tr );

			Vector screen;
			screen.Init();
			bBehindCamera = ScreenTransform(tr.endpos, screen) != 0;

			x = 0.5f * ( 1.0f + screen[0] ) * screenWidth + 0.5f;
			y = 0.5f * ( 1.0f - screen[1] ) * screenHeight + 0.5f;
		}
	}

	// MattB - angleCrosshairOffset is the autoaim angle.
	// if we're not using autoaim, just draw in the middle of the 
	// screen
	if ( angleCrosshairOffset != vec3_angle )
	{
		QAngle angles;
		Vector forward;
		Vector point, screen;

		// this code is wrong
		angles = curViewAngles + angleCrosshairOffset;
		AngleVectors( angles, &forward );
		VectorAdd( curViewOrigin, forward, point );
		ScreenTransform( point, screen );

		x += 0.5f * screen[0] * screenWidth + 0.5f;
		y += 0.5f * screen[1] * screenHeight + 0.5f;
	}

	*pX = x;
	*pY = y;
	*pbBehindCamera = bBehindCamera;
}


#ifdef NEO

void CHudCrosshair::resetPlayersCrosshair()
{
	V_memset(m_szLocalStrPlayerCrosshair, 0, sizeof(m_szLocalStrPlayerCrosshair));
	m_flLastCheckedXHair = 0.0f;
	m_iPrevPlayerIdx = -1;
}

#endif // NEO

void CHudCrosshair::Paint( void )
{
#ifdef NEO
	PaintNeo();
#else
	if ( !m_pCrosshair )
		return;

	if ( !IsCurrentViewAccessAllowed() )
		return;

	C_BasePlayer* pPlayer = C_BasePlayer::GetLocalPlayer();
	if ( !pPlayer )
		return;

	float x, y;
	bool bBehindCamera;
	GetDrawPosition ( &x, &y, &bBehindCamera, m_vecCrossHairOffsetAngle );

	if( bBehindCamera )
		return;

	float flWeaponScale = 1.f;
	int iTextureW = m_pCrosshair->Width();
	int iTextureH = m_pCrosshair->Height();
	C_BaseCombatWeapon *pWeapon = pPlayer->GetActiveWeapon();
	if ( pWeapon )
	{
		pWeapon->GetWeaponCrosshairScale( flWeaponScale );
	}

	float flPlayerScale = 1.0f;
#ifdef TF_CLIENT_DLL
	Color clr( cl_crosshair_red.GetInt(), cl_crosshair_green.GetInt(), cl_crosshair_blue.GetInt(), 255 );
	flPlayerScale = cl_crosshair_scale.GetFloat() / 32.0f;  // the player can change the scale in the options/multiplayer tab
#else
	Color clr = m_clrCrosshair;
#endif
	float flWidth = flWeaponScale * flPlayerScale * (float)iTextureW;
	float flHeight = flWeaponScale * flPlayerScale * (float)iTextureH;
	int iWidth = (int)( flWidth + 0.5f );
	int iHeight = (int)( flHeight + 0.5f );
	int iX = (int)( x + 0.5f );
	int iY = (int)( y + 0.5f );

	m_pCrosshair->DrawSelfCropped (
		iX-(iWidth/2), iY-(iHeight/2),
		0, 0,
		iTextureW, iTextureH,
		iWidth, iHeight,
		clr );
#endif // NEO
}

//-----------------------------------------------------------------------------
// Purpose: 
//-----------------------------------------------------------------------------
void CHudCrosshair::SetCrosshairAngle( const QAngle& angle )
{
	VectorCopy( angle, m_vecCrossHairOffsetAngle );
}

//-----------------------------------------------------------------------------
// Purpose: 
//-----------------------------------------------------------------------------
void CHudCrosshair::SetCrosshair( CHudTexture *texture, const Color& clr )
{
	m_pCrosshair = texture;
	m_clrCrosshair = clr;
}

//-----------------------------------------------------------------------------
// Purpose: Resets the crosshair back to the default
//-----------------------------------------------------------------------------
void CHudCrosshair::ResetCrosshair()
{
	SetCrosshair( m_pDefaultCrosshair, Color(255, 255, 255, 255) );
}
