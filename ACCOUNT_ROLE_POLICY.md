# Account role management

The users API checks both the current target role and the requested role.
Module permissions can further restrict access but cannot override these limits.

| Actor | Roles they can create/manage |
| --- | --- |
| ADMIN | ADMIN, STAFF, TEACHER, PARENT |
| STAFF | STAFF, TEACHER, PARENT within their branch |
| TEACHER | PARENT linked to students in their assigned classes |
| PARENT | Their own profile only; no role or activation changes |

Non-admins cannot manage accounts with Django `is_staff` or `is_superuser` flags.
Existing query scopes still apply when editing accounts. Changes to role do not
automatically create a missing staff or guardian profile; configure the relevant
profile when changing between staff and parent roles.

## Creating users

`POST /api/users/` keeps the existing email, password, first_name, last_name, role
fields. Non-admin callers must also supply the account's scope:

- PARENT: `student_id`, belonging to a student visible to the caller. This creates
  a guardian and a student relation with relationship `other` and is_primary=false.
- STAFF or TEACHER: `staff_profile` with `branch`, `staff_type`, `hire_date`, and
  `qualification` (plus optional staff fields). The branch must be visible to the
  caller. Email and names come from the new account. `staff_type=teacher` requires
  role TEACHER; other staff types require role STAFF. Do not supply `user` inside
  the profile.

ADMIN can continue creating accounts without these optional profile fields.
Account and profile creation is atomic. The existing staff API can also create a
staff profile and its linked login account together.

Deploy migration `users.0007_account_management_permissions` to enable users API
read/create/edit for STAFF and TEACHER, and read/edit only for PARENT. Non-admin
delete permission defaults to false. The role restrictions remain enforced if
module permissions are later changed.

## Password changes and JWT sessions

Access tokens expire after 10 minutes and carry Simple JWT's password hash claim.
Changing or resetting a password invalidates every previous access token. The
refresh endpoint also checks this claim, including for tokens absent from the
outstanding-token table.

`User.save()` blacklists the user's outstanding refresh tokens in the same
transaction as the password write. This covers the API, admin web, Django admin,
and management commands that use `set_password()` followed by `save()`. Do not
write passwords with `QuerySet.update()` or raw SQL: those bypass this hook.
Profile-only saves do not revoke sessions.

After a successful password change/reset, clients must clear their tokens and
log in again. Deploying this setting also rejects previously issued tokens that
lack the password claim, so existing users must log in again once. No new schema
migration is needed for password revocation.
