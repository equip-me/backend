from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    USER = "user"
    SUSPENDED = "suspended"


class OrganizationStatus(StrEnum):
    CREATED = "created"
    VERIFIED = "verified"


class MembershipRole(StrEnum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class MembershipStatus(StrEnum):
    CANDIDATE = "candidate"
    INVITED = "invited"
    MEMBER = "member"


class ListingStatus(StrEnum):
    HIDDEN = "hidden"
    PUBLISHED = "published"
    IN_RENT = "in_rent"
    ARCHIVED = "archived"


class OrderStatus(StrEnum):
    PENDING = "pending"
    OFFERED = "offered"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    ACTIVE = "active"
    FINISHED = "finished"
    CANCELED_BY_USER = "canceled_by_user"
    CANCELED_BY_ORGANIZATION = "canceled_by_organization"


class OrderAction(StrEnum):
    OFFER_BY_ORG = "offer_by_org"
    REJECT_BY_ORG = "reject_by_org"
    CONFIRM_BY_USER = "confirm_by_user"
    DECLINE_BY_USER = "decline_by_user"
    CANCEL_BY_USER = "cancel_by_user"
    CANCEL_BY_ORG = "cancel_by_org"
    ACTIVATE = "activate"
    FINISH = "finish"


class MediaKind(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"


class MediaOwnerType(StrEnum):
    USER = "user"
    ORGANIZATION = "organization"
    LISTING = "listing"
    MESSAGE = "message"


class MediaContext(StrEnum):
    USER_PROFILE = "user_profile"
    ORG_PROFILE = "org_profile"
    LISTING = "listing"
    CHAT = "chat"


class MediaStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
