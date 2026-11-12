"""Classping payment gateway (checkout) rules."""

# A gateway checkout must be paid within this many minutes. Only the date
# (deadline_date) is sent to the provider; Classping expires the checkout
# itself after the window, and the invoice is open for manual payment again.
PAYMENT_DEADLINE_MINUTES = 60

# The expiry check runs this many minutes after expires_at (the provider sends
# no expiry callback).
PAYMENT_EXPIRY_CHECK_DELAY_MINUTES = 2

# One checkout pays 1..N invoices of one student.
MAX_INVOICES_PER_CHECKOUT = 5

# Classping takes no fee of its own: the payer pays the provider's
# transaction fee on top, and the branch receives the full invoice total.
