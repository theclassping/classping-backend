"""Classping branch wallet and withdrawal rules."""

# OTP emailed to the branch before a withdrawal is sent to the provider.
WITHDRAWAL_OTP_LENGTH = 6
WITHDRAWAL_OTP_TTL_MINUTES = 3
WITHDRAWAL_OTP_MAX_ATTEMPTS = 3

# The status poll also checks processing withdrawals without a provider id
# (their response was lost) once they are this old, for providers whose id
# can be derived from the withdrawal (DOKU).
WITHDRAWAL_POLL_UNSENT_AFTER_MINUTES = 10

# Receives the nightly branch balance check alert (wallets.check_branch_balances).
OPS_ALERT_EMAIL = "the.class.ping@gmail.com"
