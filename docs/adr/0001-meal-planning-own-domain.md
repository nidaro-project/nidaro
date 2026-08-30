# Meal planning is its own domain; planned meals never become calendar Events

Meal planning needs a place, a time shape, and participants — which the
calendar domain already has — so modeling planned meals as calendar Events was
the plausible alternative. We decided against it: the calendar holds the
household's appointments and would be overloaded by seven-days-times-four-slots
of meal entries, and meals follow plan-edit semantics (stack a slot, swap a
dish, copy-on-plan snapshots) that don't fit event lifecycle. Meals live in
their own `meals` domain (Dish, PlannedMeal, Slot — see CONTEXT.md) with no
schema coupling to `events`; if meals should surface on a calendar view later,
that happens at the view level, not by writing Event rows.
