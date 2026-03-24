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
