from enum import Enum


class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    USER = "user"
    SUSPENDED = "suspended"


class OrganizationStatus(str, Enum):
    CREATED = "created"
    VERIFIED = "verified"


class MembershipRole(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class MembershipStatus(str, Enum):
    CANDIDATE = "candidate"
    INVITED = "invited"
    MEMBER = "member"


class ListingStatus(str, Enum):
    HIDDEN = "hidden"
    PUBLISHED = "published"
    IN_RENT = "in_rent"
    ARCHIVED = "archived"


class OrderStatus(str, Enum):
    PENDING = "pending"
    OFFERED = "offered"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    ACTIVE = "active"
    FINISHED = "finished"
    CANCELED_BY_USER = "canceled_by_user"
    CANCELED_BY_ORGANIZATION = "canceled_by_organization"
