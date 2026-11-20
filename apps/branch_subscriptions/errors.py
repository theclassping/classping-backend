"""API errors for Classping features limited by the subscription."""
from rest_framework import status

from apps.core.exceptions import CodedAPIException


class StudentLimitReached(CodedAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "STUDENT_LIMIT_REACHED"
    default_detail = "This branch has reached its student limit. Upgrade the plan to add more students."


class SubscriptionFeatureLocked(CodedAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "FEATURE_LOCKED"
    default_detail = "The subscription has expired. Renew it to continue."
