"""First-run onboarding: the wizard's completion flag and the sample-data manifest.

onboarding-001 / onboarding-002.

Two deliberately small pieces live here:

* **The wizard flag is not a column.** Whether a member has been through the
  first-run wizard is ``users.preferences["onboarding_completed"]`` — a key in
  an existing JSON column, set to ``False`` at account creation and flipped to
  ``True`` when the wizard finishes. It is per *member*, not per household: a
  partner who joins an established household months later has not been
  onboarded and must still see the wizard. A household-level flag would silently
  skip them.

* **Demo records are not tagged in place.** Tagging sample rows would mean a
  ``demo`` column on eight domain tables. Instead one manifest table,
  ``demo_data_records``, records ``(household_id, entity_type, entity_id)`` for
  every row the seeder created. Clearing deletes exactly that set — so a real
  to-do the user wrote while exploring is never in the blast radius.
"""

from life_dashboard.onboarding.models import DemoDataRecord

__all__ = ["DemoDataRecord"]
