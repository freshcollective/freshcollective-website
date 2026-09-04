from pydantic import BaseModel, EmailStr, field_validator


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required.")
        if len(v) > 100:
            raise ValueError("Name must be 100 characters or fewer.")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if len(v) > 72:
            raise ValueError("Password must be 72 characters or fewer.")
        return v


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if len(v) > 72:
            raise ValueError("Password must be 72 characters or fewer.")
        return v


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    bio: str | None = None
    display_name: str | None = None
    profile_tagline: str | None = None
    is_public: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty.")
        if len(v) > 100:
            raise ValueError("Name must be 100 characters or fewer.")
        return v

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 500:
            raise ValueError("Bio must be 500 characters or fewer.")
        return v

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) > 100:
                raise ValueError("Display name must be 100 characters or fewer.")
        return v


class CompleteOnboardingRequest(BaseModel):
    interests: list[str] = []


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if len(v) > 72:
            raise ValueError("Password must be 72 characters or fewer.")
        return v


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    email: str
    name: str | None
    role: str
    # SEC-009 — null = unverified. Frontend surfaces the verification
    # banner + resend button when this is null.
    email_verified_at: str | None = None

    @field_validator("email_verified_at", mode="before")
    @classmethod
    def _serialise_verified_at(cls, v):
        if v is None:
            return None
        # datetime → ISO string; string passes through untouched.
        return v.isoformat() if hasattr(v, "isoformat") else v


class VerifyEmailRequest(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 200:
            raise ValueError("Invalid token.")
        return v


class ProfileResponse(BaseModel):
    id: str
    email: str
    name: str | None
    role: str
    bio: str | None
    display_name: str | None
    profile_tagline: str | None
    avatar_url: str | None
    is_public: bool
    has_completed_onboarding: bool
    has_completed_creator_onboarding: bool
    interests: list[str]
    # SEC-009 — null = unverified.
    email_verified_at: str | None = None
