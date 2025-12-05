from enum import Enum
from pydantic import BaseModel

class ComplianceProfile(str, Enum):
    NONE = "NONE"
    GDPR = "GDPR"
    CCPA = "CCPA"
    HIPAA_SAFE_HARBOR = "HIPAA_SAFE_HARBOR"

class AnonymizeMode(str, Enum):
    BLUR = "blur"
    PIXELATE = "pixelate"
    BLACK_BOX = "black_box"

class PrivacyConfig(BaseModel):
    """
    Runtime configuration for the inference engine.
    """
    target_faces: bool = True
    target_plates: bool = True
    target_logos: bool = False
    target_text: bool = False
    mode: AnonymizeMode = AnonymizeMode.BLUR
    confidence_threshold: float = 0.4
    
    # Heuristic: If we find a car, should we blur the bumper area?
    # Useful if the direct plate detector misses.
    enable_heuristics: bool = True

def get_config_for_profile(profile: str, user_overrides: dict = None) -> PrivacyConfig:
    """
    Factory that generates a strictly enforced config based on the profile.
    """
    if user_overrides is None:
        user_overrides = {}
    
    # 1. Start with Default
    cfg = PrivacyConfig()
    
    # 2. Apply Profile Mandates (These cannot be disabled by user)
    if profile == ComplianceProfile.GDPR:
        cfg.target_faces = True
        cfg.target_plates = True
        cfg.target_text = True
        cfg.confidence_threshold = max(0.6, user_overrides.get("confidence_threshold", 0.6))
        
    elif profile == ComplianceProfile.HIPAA_SAFE_HARBOR:
        cfg.target_faces = True
        cfg.target_plates = True
        cfg.target_text = True
        cfg.target_logos = True
        cfg.mode = AnonymizeMode.BLACK_BOX # HIPAA requires total redaction
        cfg.confidence_threshold = max(0.7, user_overrides.get("confidence_threshold", 0.7))
        
    elif profile == ComplianceProfile.CCPA:
        cfg.target_faces = True
        cfg.target_plates = True
        cfg.confidence_threshold = max(0.55, user_overrides.get("confidence_threshold", 0.55))

    # 3. Apply User Overrides (Only if they don't violate the profile)
    # Note: We allow enabling extra targets, but not disabling mandatory ones.
    if user_overrides.get("target_logos"):
        cfg.target_logos = True
    if user_overrides.get("target_text"):
        cfg.target_text = True
    
    # Mode can be changed unless HIPAA forces Black Box
    if profile != ComplianceProfile.HIPAA_SAFE_HARBOR and "mode" in user_overrides:
        try:
            cfg.mode = AnonymizeMode(user_overrides["mode"])
        except ValueError:
            pass # Keep default if invalid mode passed

    return cfg