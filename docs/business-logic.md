# Rental Platform — Business Logic Specification

This document describes the complete business logic of the rental platform. It is intended as a rebuild blueprint: an AI agent or developer should be able to reimplement the system from scratch using any technology stack while preserving all described behavior.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Users & Authentication](#2-users--authentication)
3. [Organizations](#3-organizations)
4. [Listing Catalog](#4-listing-catalog)
5. [Order Lifecycle](#5-order-lifecycle)
6. [Media & File Uploads](#6-media--file-uploads)
7. [Data Model Reference](#7-data-model-reference)

---

## 1. Overview

### Platform Purpose

A B2B/B2C marketplace for renting equipment and other assets. Two actor types interact:

- **Users (renters)** — browse the listing catalog, place rental orders, and confirm or decline offers.
- **Organizations (owners)** — list rentable items, process incoming orders, offer terms, and manage their catalog.

### High-Level Flow

1. An **Organization** is created and verified by a platform admin.
2. Organization editors publish **Listings** in the catalog.
3. A **User** finds a published listing and creates an **Order**.
4. The organization reviews the order, optionally adjusts terms (cost, dates), and offers it back.
5. The user confirms or declines. If confirmed, the rental proceeds for the agreed dates.
6. Either party can cancel a confirmed or active order.

### External Integrations

| Service | Purpose |
|---------|---------|
| **Dadata** | Auto-fill organization legal data by INN (Russian tax ID) |

---

## 2. Users & Authentication

### 2.1 User Data Model

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | |
| email | string | unique, required | Login identifier |
| hashed_password | string | required | Argon2id hash |
| phone | string | required | Russian format |
| name | string | required | First name |
| middle_name | string | nullable | Patronymic |
| surname | string | required | Last name |
| role | enum UserRole | default: `user` | Platform-level role |
| created_at | datetime | auto, immutable | Registration timestamp |

### 2.2 Registration Validation Rules

Registration is the same for all users regardless of their future role. After registration, the user is prompted: "Want to create an organization or join an existing one to publish listings?"

**Email:** must be a valid email format.

**Phone:** Russian mobile number format. Regex pattern:
- Starts with `+7`, `7`, or `8` (optional)
- Area code first digit must be `4`, `8`, or `9`
- Total 10 digits after country code
- Optional spaces/dashes/parentheses as formatting

**Password:**
- Minimum 8 characters
- At least one lowercase letter (Latin `a-z` or Cyrillic `а-я`)
- At least one uppercase letter (Latin `A-Z` or Cyrillic `А-Я`)
- At least one digit

**Duplicate check:** email must be unique across all users (409 Conflict on duplicate).

### 2.3 User Update Rules

- All fields are optional on update (partial update).
- **Email change** must pass format validation and uniqueness check (409 Conflict on duplicate).
- **Password change** requires both `password` (current) and `new_password`. The current password is verified via authentication. The new password must pass the same strength rules as registration.
- Providing `password` without `new_password` is an error.

### 2.4 Authentication

**Mechanism:** JWT Bearer tokens.

- **Algorithm:** HS256
- **Token payload:** `sub` = user ID (UUID string), `exp` = expiration timestamp
- **Token lifetime:** 7 days from issuance
- **Login:** email + password. Returns `access_token` and `token_type: "bearer"`.

**Failed login:** returns 401 `"Incorrect username or password"` for both wrong email and wrong password (no information leak).

**Expired/invalid token:** returns 401 `"Could not validate credentials"`.

**Suspended user:** returns 403 `"Account suspended"` (blocked after token validation, before route logic).

### 2.5 Permission Levels

The system uses a layered permission model. Each level builds on the previous:

| Level | Requirements |
|-------|-------------|
| **Public** | No authentication needed |
| **Authenticated** | Valid JWT + role is not `suspended` |
| **Org Editor** | Authenticated + `editor` or `admin` membership in the relevant organization |
| **Org Admin** | Authenticated + `admin` membership in the relevant organization |
| **Platform Admin** | Authenticated + user `role` is `admin` or `owner` |

**Permission error codes:**
- No/invalid token → 401
- Suspended user → 403
- Insufficient org membership → 403
- Insufficient platform role → 403

### 2.6 User API Summary

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/users/` | Public | Register new user |
| GET | `/api/v1/users/{user_id}` | Public | Get user by ID |
| GET | `/api/v1/users/me` | Authenticated | Get current user profile |
| PATCH | `/api/v1/users/me` | Authenticated | Update current user |
| PATCH | `/api/v1/private/users/{user_id}/role` | Platform Admin | Change user role (including suspend/unsuspend) |
| GET | `/api/v1/private/users/` | Platform Admin | List all users (paginated, searchable, role filter) |

---

## 3. Organizations

### 3.1 Organization Data Model

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | |
| inn | string | unique, required | Russian tax ID (10 or 12 digits) |
| short_name | string | nullable | Short legal name |
| full_name | string | nullable | Full legal name with legal form |
| registration_date | date | nullable | Date of state registration |
| authorized_capital_k_rubles | decimal | nullable | Authorized capital in thousands of rubles |
| legal_address | string | nullable | Registered legal address |
| manager_name | string | nullable | CEO / manager full name |
| main_activity | string | nullable | Primary OKVED code |
| dadata_response | JSON | nullable | Full Dadata API response stored as-is |
| status | enum OrganizationStatus | default: `created` | Verification lifecycle state |

#### Organization Contact Model (1:N)

Each organization has one or more contacts used for platform admin verification and communication. At least one of `phone` or `email` must be provided per contact.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | |
| organization | FK → Organization | required | |
| display_name | string | required | Contact name — person or department (e.g., "Rental Department") |
| phone | string | nullable | Contact phone (required if no email) |
| email | string | nullable | Contact email (required if no phone) |

#### Payment Details Model (1:1)

Banking details for the organization. Optional — added when the organization is ready to receive payments.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | |
| organization | FK → Organization | required, unique | One-to-one with Organization |
| payment_account | string | required | Settlement account number |
| bank_bic | string | required | Bank identification code |
| bank_inn | string | required | Bank's tax ID |
| bank_name | string | required | Bank name |
| bank_correspondent_account | string | required | Correspondent account number |

### 3.2 Organization Membership

Users interact with organizations through a many-to-many membership model. A user can be a member of multiple organizations simultaneously.

#### Membership Model

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | |
| user | FK → User | required | |
| organization | FK → Organization | required | |
| role | enum MembershipRole | required | Permission level within the org |
| status | enum MembershipStatus | required | Membership lifecycle state |
| created_at | datetime | auto | |
| updated_at | datetime | auto | |

Unique constraint: `(user, organization)` — a user can have at most one membership record per organization.

**MembershipRole:** `admin`, `editor`, `viewer`

| Role | Permissions |
|------|------------|
| `admin` | Invite/remove members, change roles, all editor permissions |
| `editor` | Create and manage listings, process orders |
| `viewer` | View organization's internal data (listings in any status, orders) |

**MembershipStatus:** `candidate`, `invited`, `member`

| Status | Description |
|--------|------------|
| `candidate` | User requested to join; awaiting org admin approval |
| `invited` | Org admin invited the user for a specific role; awaiting user acceptance |
| `member` | Active member |

#### Membership Business Rules

- **Creating an organization** automatically makes the creator a `member` with role `admin`.
- **Joining:** user sends a join request → status `candidate` → org admin approves and assigns a role → status `member`. The user does not choose a role; the admin decides.
- **Inviting:** org admin invites a user for a specific role → status `invited` → user accepts → status `member`.
- Only org `admin` can invite users, approve candidates, remove members, and change roles.

#### Membership API

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/organizations/{org_id}/members/invite` | Org Admin | Invite a user for a role |
| POST | `/api/v1/organizations/{org_id}/members/join` | Authenticated | Request to join |
| PATCH | `/api/v1/organizations/{org_id}/members/{id}/approve` | Org Admin | Approve candidate (admin assigns role in body) |
| PATCH | `/api/v1/organizations/{org_id}/members/{id}/accept` | Authenticated (invited user) | Accept invitation |
| PATCH | `/api/v1/organizations/{org_id}/members/{id}/role` | Org Admin | Change member role |
| DELETE | `/api/v1/organizations/{org_id}/members/{id}` | Org Admin or Self | Remove member, cancel request, or decline invite |
| GET | `/api/v1/organizations/{org_id}/members` | Org Member (any role) | List members |

### 3.3 Organization Creation

The user provides an **INN** and **at least one contact** (each contact requires `display_name` and at least one of `phone` or `email`). Contacts are included inline in the creation request.

**Creation flow:**

1. **Validate** the request schema (INN format, contacts present and valid).
2. **Begin transaction:**
   1. Call the **Dadata API** with the provided INN. If Dadata is **unreachable or returns an error** — abort the transaction and fail with 502 Bad Gateway.
   2. Create the `Organization` from the Dadata response. The full response is stored in `dadata_response`; a subset is extracted into top-level fields:

   | Dadata field path | Maps to |
   |-------------------|---------|
   | `data.name.short_with_opf` | `short_name` |
   | `data.name.full_with_opf` | `full_name` |
   | `data.inn` | `inn` |
   | `data.state.registration_date` | `registration_date` |
   | `data.address.value` | `legal_address` |
   | `data.management.name` | `manager_name` |
   | `data.okved` | `main_activity` |

   3. Create `OrganizationContact` records for this organization.
   4. Create the creator's `Membership` (role `admin`, status `member`).
3. **Commit transaction.** New organizations start with status `created`.

### 3.4 Organization Contacts Update

Contacts are updated via a dedicated endpoint (`PUT`). Individual contact records are **immutable** — the endpoint accepts a complete new contacts list that **replaces** all existing contacts for the organization. The frontend pre-fills this list from the current contacts so the user only edits what they need. The same validation rules apply: at least one contact, each with `display_name` and at least one of `phone` or `email`.

### 3.5 Payment Details

Payment details are added to an organization after creation via a dedicated endpoint. Only an **Org Admin** can create or update them. Each organization has at most one `PaymentDetails` record.

### 3.6 Organization Verification Lifecycle

| Status | Description |
|--------|------------|
| `created` | Pending platform admin verification |
| `verified` | Verified by platform admin |

**While `created`:**
- The organization functions normally for its members (they can create/edit listings, manage membership).
- Listings belonging to this organization are **excluded from the public catalog** (search and browse).
- Direct access to a listing from an unverified org by a non-member returns **403**.
- **Orders cannot be placed** for listings belonging to unverified organizations.

**Verification:**
- A platform admin reviews the organization's contact information and verifies the org.
- Once `verified`, the organization's published listings become visible in the public catalog and can receive orders.

### 3.7 Organization API Summary

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/organizations/` | Authenticated | Create organization with contacts (creator becomes admin member) |
| GET | `/api/v1/organizations/` | Public | List verified organizations with published listing count |
| GET | `/api/v1/organizations/{id}` | Public | Get organization by ID |
| GET | `/api/v1/users/me/organizations` | Authenticated | List organizations the current user belongs to |
| PUT | `/api/v1/organizations/{org_id}/contacts` | Org Admin | Replace all contacts with a new list |
| GET | `/api/v1/organizations/{org_id}/payment-details` | Org Member | Get payment details (404 if not set) |
| POST | `/api/v1/organizations/{org_id}/payment-details` | Org Admin | Create or replace payment details |
| PATCH | `/api/v1/private/organizations/{id}/verify` | Platform Admin | Verify organization |

---

## 4. Listing Catalog

### 4.1 Listing Data Model

A "Listing" is a rentable item published by an organization.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | |
| name | string | required | Listing display name |
| category | FK → ListingCategory | required | Listing type |
| price | float | required | Rental price per day |
| description | text | nullable | Public description |
| specifications | JSON (key-value map) | nullable | Additional specs (e.g., year, power, dimensions) |
| status | enum ListingStatus | default: `hidden` | Visibility/availability |
| organization | FK → Organization | required, cascade delete | Owning organization |
| added_by | FK → User | required | User who created the listing |
| with_operator | boolean | default: false | Comes with operator |
| on_owner_site | boolean | default: false | Must be used at owner's location |
| delivery | boolean | default: false | Delivery available |
| installation | boolean | default: false | Installation service included |
| setup | boolean | default: false | Setup/configuration included |
| created_at | datetime | auto, immutable | |
| updated_at | datetime | auto-updated | |

**Default ordering:** most recently updated first (`-updated_at`).

### 4.2 Listing Statuses

| Status | Value | Description |
|--------|-------|-------------|
| HIDDEN | `hidden` | Default. Not visible in public catalog |
| PUBLISHED | `published` | Visible in public catalog, available for ordering |
| IN_RENT | `in_rent` | Currently being rented (set automatically by order lifecycle or manually by editor) |
| ARCHIVED | `archived` | Removed from catalog by owner |

### 4.3 Listing Categories

Categories organize listings into types. They have two sources:

**Seed categories** (loaded on first startup if DB is empty):

| Name (Russian) | English equivalent |
|---------------|-------------------|
| Спецтехника | Special equipment |
| Промышленное оборудование | Industrial equipment |
| Контрактное производство | Contract manufacturing |
| Выставочное оборудование | Exhibition equipment |

Seed categories are created with `verified = true` and no organization.

**User-created categories:** any organization editor can create a new category scoped to their organization. User-created categories have `verified = false`.

**Category listing rules:**
- **Public listing (no org filter):** returns only `verified = true` categories, ordered by listing count descending.
- **Organization-specific listing:** returns categories that have listings belonging to that organization, plus all `verified = true` categories, ordered by listing count descending.

Category model:

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | |
| name | string | required | |
| organization | FK → Organization | nullable | Null for seed/global categories |
| added_by | FK → User | nullable | |
| created_at | datetime | auto | |
| verified | boolean | default: false | |

### 4.4 Listing Visibility Rules

| Viewer | What they see |
|--------|---------------|
| **Public (unauthenticated)** | Only listings with status `PUBLISHED` from **verified** organizations. Filterable by `category_id` and `organization_id`. |
| **Organization member (any role)** | All listings belonging to their organization (any status, regardless of org verification). |

Listings from unverified organizations are invisible to non-members. Direct access by a non-member returns **403**.

### 4.5 Listing Permission Rules

| Action | Required permission |
|--------|-------------------|
| **Create** | Org Editor |
| **Update** | Org Editor (same organization) |
| **Delete** | Org Editor (same organization) |
| **Change status** | Org Editor (same organization) |
| **Create category** | Org Editor (same organization) |
| **View single item** | Public (verified org only) or Org Member |
| **List public catalog** | Public |
| **List organization's listings** | Org Member (any role) |

### 4.6 Listing API Summary

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/organizations/{org_id}/listings/` | Org Editor | Create listing |
| PATCH | `/api/v1/organizations/{org_id}/listings/{id}` | Org Editor | Update listing |
| DELETE | `/api/v1/organizations/{org_id}/listings/{id}` | Org Editor | Delete listing |
| PATCH | `/api/v1/organizations/{org_id}/listings/{id}/status` | Org Editor | Change listing status |
| GET | `/api/v1/organizations/{org_id}/listings/` | Org Member | List organization's listings |
| GET | `/api/v1/listings/` | Public | Browse published listings (verified orgs only) |
| GET | `/api/v1/listings/{id}` | Public | Get single listing |
| GET | `/api/v1/listings/categories/` | Public | List verified (global) categories |
| GET | `/api/v1/organizations/{org_id}/listings/categories/` | Org Member | List org's categories (including global) |
| POST | `/api/v1/organizations/{org_id}/listings/categories/` | Org Editor | Create category for the organization |

---

## 5. Order Lifecycle

An order represents a rental request from a user for a specific listing owned by an organization. The flow is intentionally simple: request → offer → confirm → rent → finish.

### 5.1 Order Data Model

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | string(6) | PK, short ID | 6-character alphanumeric |
| listing | FK → Listing | required | The rented listing |
| organization | FK → Organization | required | Organization that owns the listing |
| requester | FK → User | required | User who placed the order |
| requested_start_date | date | required | User's requested rental start date |
| requested_end_date | date | required | User's requested rental end date |
| status | enum OrderStatus | default: `pending` | Current lifecycle stage |
| estimated_cost | decimal | nullable | Auto-calculated from requested dates and listing price |
| offered_cost | decimal | nullable | Organization's offered cost (required to transition to `offered`) |
| offered_start_date | date | nullable | Organization's offered start date (required to transition to `offered`) |
| offered_end_date | date | nullable | Organization's offered end date (required to transition to `offered`) |
| created_at | datetime | auto | |
| updated_at | datetime | auto-updated | |

### 5.2 Order Status State Machine

There are 9 statuses:

```
PENDING
  ├──[org editor: offer]───────────► OFFERED
  │                                    ├──[org editor: re-offer]──► OFFERED (updated terms)
  │                                    ├──[user: confirm]──► CONFIRMED
  │                                    │                       ├──[auto: offered_start_date arrives]──► ACTIVE
  │                                    │                       │                                         ├──[auto: offered_end_date passes]──► FINISHED
  │                                    │                       │                                  ├──[user: cancel]──► CANCELED_BY_USER
  │                                    │                       │                                  └──[org: cancel]──► CANCELED_BY_ORGANIZATION
  │                                    │                       ├──[user: cancel]──► CANCELED_BY_USER
  │                                    │                       └──[org: cancel]──► CANCELED_BY_ORGANIZATION
  │                                    └──[user: decline]──► DECLINED
  └──[org editor: reject]─────────► REJECTED
```

**Terminal statuses** (no further transitions): `finished`, `rejected`, `declined`, `canceled_by_user`, `canceled_by_organization`.

### 5.3 Transition Rules (Detailed)

#### Order Creation
- **Who:** Any authenticated user
- **Preconditions:**
  - Listing must exist and have status `PUBLISHED`
  - Listing must belong to a **verified** organization
  - `requested_start_date` must not be in the past
  - `requested_start_date` must be ≤ `requested_end_date`
- **Side effects:**
  - `estimated_cost` is auto-calculated: `price_per_day x ((requested_end_date - requested_start_date).days + 1)`, rounded to 2 decimal places
  - `organization` is set to the listing's owning organization
- **Result:** Order created with status `pending`

#### Organization Offers Terms
- **Who:** Org Editor (listing's organization)
- **Required status:** `pending` or `offered` (re-offer to update terms before user decides)
- **Required fields:** `offered_cost` (must be positive), `offered_start_date`, `offered_end_date` (start ≤ end). All three must be provided. The frontend pre-fills them from `estimated_cost`, `requested_start_date`, `requested_end_date`; the editor adjusts if needed.
- **Transition:** → `offered`
- **Semantics:** After the user confirms the order, the `offered_*` fields become the **source of truth** for the rental terms (cost, start date, end date).

#### Organization Rejects Order
- **Who:** Org Editor
- **Required status:** `pending`
- **Transition:** → `rejected`

#### User Confirms Order
- **Who:** Requester (the user who placed the order)
- **Required status:** `offered`
- **Transition:** → `confirmed`
- **Business meaning:** User agrees to the (possibly adjusted) terms

#### User Declines Order
- **Who:** Requester
- **Required status:** `offered`
- **Transition:** → `declined`
- **Business meaning:** User does not agree with the offered terms

#### Automatic: Rent Starts
- **Trigger:** `today >= offered_start_date` (currently implemented as lazy evaluation on read; planned migration to Temporal workflow)
- **Required status:** `confirmed`
- **Transition:** → `active`
- **Side effect:** Listing status is set to `in_rent`

#### Automatic: Rent Ends
- **Trigger:** `today > offered_end_date` (lazy evaluation on read)
- **Required status:** `active`
- **Transition:** → `finished`
- **Side effect:** Listing status returns to `published`
- **Chaining:** If both dates have passed when an order is read (e.g., confirmed while offline), the transitions chain: `confirmed → active → finished` in a single read. The listing ends at `published` (skipping the transient `in_rent` state).

#### User Cancels Order
- **Who:** Requester
- **Allowed in:** `confirmed` or `active`
- **Transition:** → `canceled_by_user`
- **Side effect:** If listing was `in_rent`, its status returns to `published`

#### Organization Cancels Order
- **Who:** Org Editor
- **Allowed in:** `confirmed` or `active`
- **Transition:** → `canceled_by_organization`
- **Side effect:** If listing was `in_rent`, its status returns to `published`

### 5.4 Per-Order Chat

Each order should have a dedicated chat room between the renter and the organization, allowing them to communicate throughout the order lifecycle. The chat implementation is out of scope for this document and will be designed separately.

### 5.5 Order Access Rules

**User-side access:**
- The user is the order's `requester`.

**Organization-side access:**
- The user has `editor` or `admin` membership in the order's `organization`.

### 5.6 Order API Summary

**User (renter) endpoints:**

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/orders/` | Authenticated | Place order for a listing |
| GET | `/api/v1/orders/` | Authenticated | List my orders |
| GET | `/api/v1/orders/{id}` | Authenticated (requester) | Get order detail |
| PATCH | `/api/v1/orders/{id}/confirm` | Authenticated (requester) | Accept the offered terms |
| PATCH | `/api/v1/orders/{id}/decline` | Authenticated (requester) | Decline the offered terms |
| PATCH | `/api/v1/orders/{id}/cancel` | Authenticated (requester) | Cancel confirmed/active order |

**Organization (owner) endpoints:**

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/organizations/{org_id}/orders/` | Org Editor | List incoming orders |
| GET | `/api/v1/organizations/{org_id}/orders/{id}` | Org Editor | Get order detail |
| PATCH | `/api/v1/organizations/{org_id}/orders/{id}/offer` | Org Editor | Accept and offer terms (cost, dates) |
| PATCH | `/api/v1/organizations/{org_id}/orders/{id}/reject` | Org Editor | Reject order |
| PATCH | `/api/v1/organizations/{org_id}/orders/{id}/cancel` | Org Editor | Cancel confirmed/active order |

---

## 6. Media & File Uploads

### 6.1 Media Entity

Each uploaded file is tracked as a `Media` record.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | |
| kind | enum MediaKind | required | File type category |
| context | enum MediaContext | required | Purpose / usage context |
| status | enum MediaStatus | default: `pending_upload` | Processing lifecycle state |
| owner_type | string | required | Entity type that owns this file (e.g. `user`, `organization`, `listing`) |
| owner_id | string | required | ID of the owning entity |
| s3_key | string | required | S3 object key for the original upload |
| uploaded_by | FK → User | required | User who initiated the upload |
| created_at | datetime | auto | |
| updated_at | datetime | auto-updated | |

#### MediaKind
| Value | Description |
|-------|-------------|
| `photo` | Image file |
| `video` | Video file |
| `document` | Document file (PDF, etc.) |

#### MediaContext
| Value | Description |
|-------|-------------|
| `user_profile` | User profile photo |
| `org_profile` | Organization profile photo |
| `listing` | Listing photo, video, or document |

#### MediaStatus
| Value | Description |
|-------|-------------|
| `pending_upload` | Presigned URL issued; waiting for S3 upload |
| `processing` | Upload confirmed; ARQ worker is transcoding/resizing |
| `ready` | Processing complete; file(s) available |
| `failed` | Processing failed; kept for inspection, not auto-deleted |

**Status state machine:**

```
pending_upload
  └──[POST /media/{id}/confirm]──► processing
                                      ├──[worker success]──► ready
                                      └──[worker failure]──► failed
                                                               └──[POST /media/{id}/retry]──► processing
```

### 6.2 Upload Flow

1. Client calls `POST /media/upload-url` with `kind`, `context`, and `owner_id`. Server creates a `Media` record (`status: pending_upload`) and returns a presigned S3 PUT URL.
2. Client uploads the file directly to S3 using the presigned URL (no server proxy).
3. Client calls `POST /media/{id}/confirm`. Server transitions status to `processing` and enqueues an ARQ background job.
4. ARQ worker processes the file (transcode/resize), stores output variants in S3, and transitions status to `ready` or `failed`.
5. Client polls `GET /media/{id}/status` until `ready` or `failed`.

### 6.3 Processing Rules

#### Photos
Output format: **WebP**.

| Context | Variants produced |
|---------|-------------------|
| `user_profile` | `medium` (400×400), `small` (100×100) |
| `org_profile` | `medium` (400×400), `small` (100×100) |
| `listing` | `large` (1200×900), `medium` (600×450), `small` (300×225) |

#### Videos
Output format: **WebM** (VP9 video + Opus audio).

| Variant | Resolution | Duration | Audio |
|---------|------------|----------|-------|
| `full` | 720p | full | yes |
| `preview` | 480p | first 10 s | no |

#### Documents
Stored as-is. No server-side processing; the original S3 object is the deliverable.

### 6.4 Entity Media Associations

| Entity | Allowed kinds | Cardinality |
|--------|--------------|-------------|
| User | photo | 0–1 profile photo |
| Organization | photo | 0–1 profile photo |
| Listing | photo, video, document | multiple (configurable limits per kind) |

Setting a new profile photo for a User or Organization replaces the existing one; the old `Media` record and its S3 objects are deleted.

### 6.5 Cleanup

| Trigger | Scope | Behavior |
|---------|-------|---------|
| Entity deleted | All attached `Media` records | Immediate deletion: S3 objects and DB records removed synchronously |
| Orphan sweep (hourly cron) | `status: pending_upload`, `owner_id` not attached to any entity, `created_at` older than TTL (default 24 h) | Deleted by background job |
| Failed media | `status: failed` | **Not** auto-deleted; retained for manual inspection |

### 6.6 Permissions

| Action | Required permission |
|--------|-------------------|
| Request presigned upload URL | Authenticated |
| Confirm upload | Uploader only |
| Get status | Uploader only |
| Delete media | Uploader only |
| Retry failed processing | Uploader only |
| Attach to User profile | Uploader = the user themselves |
| Attach to Organization profile | Uploader + Org Admin of that organization |
| Attach to Listing | Uploader + Org Editor of the listing's organization |

### 6.7 Media API Summary

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/media/upload-url` | Authenticated | Request presigned S3 PUT URL; creates Media record |
| POST | `/api/v1/media/{id}/confirm` | Uploader | Confirm upload complete; trigger processing |
| GET | `/api/v1/media/{id}/status` | Uploader | Poll processing status |
| DELETE | `/api/v1/media/{id}` | Uploader | Delete media record and S3 objects |
| POST | `/api/v1/media/{id}/retry` | Uploader | Re-enqueue processing for a failed media |
| PATCH | `/api/v1/organizations/{id}/photo` | Org Admin | Attach a ready photo as the organization's profile photo |

---

## 7. Data Model Reference

### 7.1 Entity Relationships

```
Organization (PK: id)
  ├── 1:N ── OrganizationContact (organization FK)
  ├── 1:1 ── PaymentDetails (organization FK, unique)
  ├── 1:N ── OrganizationMembership (organization FK)
  ├── 1:N ── Listing (organization FK)
  ├── 1:N ── ListingCategory (organization FK, nullable)
  └── 1:N ── Order (organization FK)

OrganizationContact (PK: id)
  └── FK ── Organization

PaymentDetails (PK: id)
  └── FK ── Organization (unique)

User (PK: id)
  ├── 1:N ── OrganizationMembership (user FK)
  ├── 1:N ── Listing (added_by FK)
  ├── 1:N ── ListingCategory (added_by FK)
  └── 1:N ── Order (requester FK)

OrganizationMembership (PK: id)
  ├── FK ── User
  └── FK ── Organization
  Unique: (user, organization)

ListingCategory (PK: id)
  └── 1:N ── Listing (category FK)

Listing (PK: id)
  ├── FK ── Organization
  ├── FK ── User (added_by)
  ├── FK ── ListingCategory (category)
  └── 1:N ── Order (listing FK)

Order (PK: id)
  ├── FK ── Listing
  ├── FK ── Organization
  └── FK ── User (requester)

Media (PK: id)
  └── FK ── User (uploaded_by)
  Polymorphic: (owner_type, owner_id) → User | Organization | Listing
```

### 7.2 All Enums

#### UserRole
| Value | Description |
|-------|-------------|
| `owner` | Platform owner. Can manage admins. |
| `admin` | Platform admin. Can verify organizations, suspend users. |
| `user` | Default role for all new registrations. |
| `suspended` | Account suspended. Cannot authenticate (returns 403). |

#### OrganizationStatus
| Value | Description |
|-------|-------------|
| `created` | Pending platform admin verification |
| `verified` | Verified by platform admin |

#### MembershipRole
| Value | Description |
|-------|-------------|
| `admin` | Organization admin. Can manage members and all editor actions. |
| `editor` | Can create/manage listings and process orders. |
| `viewer` | Read-only access to org's internal data. |

#### MembershipStatus
| Value | Description |
|-------|-------------|
| `candidate` | User requested to join; awaiting org admin approval |
| `invited` | Org admin invited the user; awaiting user acceptance |
| `member` | Active member |

#### ListingStatus
| Value | Description |
|-------|-------------|
| `hidden` | Not visible in public catalog (default for new listings) |
| `published` | Visible in public catalog, available for ordering |
| `in_rent` | Currently being rented (set automatically by order lifecycle or manually by editor) |
| `archived` | Removed from catalog by owner |

#### OrderStatus
| Value | Description |
|-------|-------------|
| `pending` | Initial state. Awaiting organization response. |
| `offered` | Organization accepted and proposed terms. Awaiting user decision. |
| `rejected` | Organization rejected the order. Terminal. |
| `confirmed` | User accepted the offer. Awaiting rental start. |
| `declined` | User declined the offer. Terminal. |
| `active` | Rental in progress (offered_start_date has arrived). |
| `finished` | Rental complete (offered_end_date has passed). Terminal. |
| `canceled_by_user` | Canceled by the user. Terminal. |
| `canceled_by_organization` | Canceled by the organization. Terminal. |

#### OrderAction
| Value | Actor | Description |
|-------|-------|-------------|
| `offer_by_org` | Organization | Offer or re-offer rental terms |
| `reject_by_org` | Organization | Reject the order request |
| `confirm_by_user` | User | Accept the offered terms |
| `decline_by_user` | User | Decline the offered terms |
| `cancel_by_user` | User | Cancel a confirmed or active order |
| `cancel_by_org` | Organization | Cancel a confirmed or active order |
| `activate` | System | Rental period starts (lazy eval / Temporal) |
| `finish` | System | Rental period ends (lazy eval / Temporal) |

#### MediaKind
| Value | Description |
|-------|-------------|
| `photo` | Image file |
| `video` | Video file |
| `document` | Document file (PDF, etc.) |

#### MediaContext
| Value | Description |
|-------|-------------|
| `user_profile` | User profile photo |
| `org_profile` | Organization profile photo |
| `listing` | Listing photo, video, or document |

#### MediaStatus
| Value | Description |
|-------|-------------|
| `pending_upload` | Presigned URL issued; waiting for S3 upload |
| `processing` | Upload confirmed; ARQ worker is transcoding/resizing |
| `ready` | Processing complete; file(s) available |
| `failed` | Processing failed; kept for inspection, not auto-deleted |
