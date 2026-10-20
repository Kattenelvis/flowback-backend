import logging
import uuid

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q, Count, Model
from django.shortcuts import get_object_or_404
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from rest_framework.exceptions import NotFound, ValidationError

from backend.settings import DEFAULT_FROM_EMAIL, URL_USER_CREATE, URL_USER_FORGOT_PASSWORD, EMAIL_HOST
from flowback.common.services import model_update, get_object
from flowback.group.models import GroupThread
from flowback.kanban.services import KanbanManager
from flowback.notification.models import NotificationChannel
from flowback.poll.models import Poll
from flowback.schedule.services import schedule_event_create, schedule_event_update, schedule_event_delete
from flowback.user.models import User, OnboardUser, PasswordReset, Report, UserBookmark

user_kanban = KanbanManager(origin_type='user')


def user_create(*, email: str) -> OnboardUser | None:
    email = email.lower()
    users = User.objects.filter(email=email)
    if users.exists():
        for onboard_user in users:
            if onboard_user.email == email:
                raise ValidationError('Email already exists.')

            else:
                raise ValidationError('Username already exists.')

    onboard_user, created = OnboardUser.objects.update_or_create(email=email,
                                                                 defaults=dict(is_verified=False,
                                                                               verification_code=uuid.uuid4()))

    link = f'Use this code to create your account: {onboard_user.verification_code}'
    if URL_USER_CREATE:
        link = (f"Use this link to create your account: {URL_USER_CREATE}"
                f"?verification_code={onboard_user.verification_code}")

    if EMAIL_HOST:
        send_mail('Flowback Verification Code', link, DEFAULT_FROM_EMAIL, [email])

    else:
        logging.info("Email host not configured. Email not sent, but code was sent to the console.")
        print(f"Verification code for '{onboard_user.email}': {onboard_user.verification_code}")

    return onboard_user


def user_create_verify(*, username: str, verification_code: str, password: str):
    onboard_user = get_object_or_404(OnboardUser, verification_code=verification_code)

    if User.objects.filter(email=onboard_user.email).exists():
        raise ValidationError('Email already registered')

    elif User.objects.filter(username=username).exists():
        raise ValidationError('Username already registered')

    elif onboard_user.is_verified:
        raise ValidationError('Verification code has already been used.')

    validate_password(password)

    user = User.objects.create_user(username=username, email=onboard_user.email, password=password)

    model_update(instance=onboard_user, fields=['is_verified'], data=dict(is_verified=True))

    return user


def user_forgot_password(*, email: str) -> PasswordReset:
    user = get_object_or_404(User, email=email)

    password_reset = PasswordReset.objects.create(user=user)

    link = f'Use this code to reset your account password: {password_reset.verification_code}'

    if URL_USER_FORGOT_PASSWORD:
        link = (f'Use this link to reset your account password: {URL_USER_FORGOT_PASSWORD}'
                f'?verification_code={password_reset.verification_code}')

    if EMAIL_HOST:
        send_mail('Flowback Verification Code', link, DEFAULT_FROM_EMAIL, [email])

    else:
        logging.info("Email host not configured. Email not sent, but code was sent to the console.")
        print(f"Verification code for '{user.username}': {password_reset.verification_code}")

    return password_reset


def user_forgot_password_verify(*, verification_code: str, password: str):
    password_reset = get_object_or_404(PasswordReset, verification_code=verification_code)

    if password_reset.is_verified:
        raise ValidationError('Verification code has already been used.')

    validate_password(password)
    user = password_reset.user
    user.set_password(password)
    user.save()

    model_update(instance=password_reset, fields=['is_verified'], data=dict(is_verified=True))

    return user


def user_update(*, user: User, data) -> User:
    non_side_effects_fields = [
        'username',
        'email',
        'profile_image',
        'banner_image',
        'bio',
        'website',
        'email_notifications',
        'dark_theme',
        'contact_email',
        'contact_phone',
        'user_config',
        'public_status',
        'chat_status'
    ]

    user, has_updated = model_update(instance=user, fields=non_side_effects_fields, data=data)

    return user


def user_delete(*, user_id: int) -> None:
    user = get_object(User, id=user_id)

    if user.is_active:
        user.is_active = False
        user.username = 'deleted_user_' + uuid.uuid4().hex
        user.email = user.username + '@example.com'
        user.profile_image = None
        user.banner_image = None
        user.email_notifications = False
        user.bio = None
        user.website = None

        user.full_clean()
        user.save()

        user.kanban.delete()
        OnboardUser.objects.filter(email=user.email).delete()


def user_notification_subscribe(*, user: User, **kwargs):
    user.notification_channel.subscribe(user=user, **kwargs)


def user_kanban_entry_create(*,
                             user_id: int,
                             assignee_id: int = None,
                             title: str,
                             description: str = None,
                             attachments: list = None,
                             priority: int,
                             lane: int,
                             end_date: timezone.datetime = None):
    return user_kanban.kanban_entry_create(origin_id=user_id,
                                           created_by_id=user_id,
                                           assignee_id=assignee_id,
                                           title=title,
                                           description=description,
                                           attachments=attachments,
                                           priority=priority,
                                           end_date=end_date,
                                           lane=lane)


def user_kanban_entry_update(*, user_id: int, entry_id: int, data):
    return user_kanban.kanban_entry_update(origin_id=user_id, entry_id=entry_id, data=data)


def user_kanban_entry_delete(*, user_id: int, entry_id: int):
    return user_kanban.kanban_entry_delete(origin_id=user_id, entry_id=entry_id)


def report_create(*,
                  user_id: int,
                  title: str,
                  description: str,
                  group_id: int = None,
                  post_id: int = None,
                  post_type: str = None):
    user = get_object(User, id=user_id)

    report = Report(user=user,
                    title=title,
                    description=description,
                    group_id=group_id,
                    post_id=post_id,
                    post_type=post_type)
    report.full_clean()
    report.save()

    return report


def report_update(*, report_id: int, **data):
    report = Report.objects.get(id=report_id)
    non_side_effects_fields = ['title', 'description', 'action_description', 'group_id', 'post_id', 'post_type']

    report, has_updated = model_update(instance=report, fields=non_side_effects_fields, data=data)
    return report


def user_schedule_event_create(user: User, **data):
    data['schedule_id'] = user.schedule.id
    return schedule_event_create(created_by=user, **data)


def user_schedule_event_update(user: User, **data):
    data['schedule_id'] = user.schedule.id
    return schedule_event_update(**data)


def user_schedule_event_delete(user: User, **data):
    data['schedule_id'] = user.schedule.id
    return schedule_event_delete(**data)


# Maps the content_type clients send to the model and the UserBookmark field that points at it
BOOKMARK_TARGETS = {'poll': (Poll, 'poll'),
                    'groupthread': (GroupThread, 'thread')}


def _user_bookmark_target(content_type: str) -> tuple[type[Model], str]:
    try:
        return BOOKMARK_TARGETS[content_type.lower()]

    except KeyError:
        raise ValidationError(f'content_type must be one of: {", ".join(BOOKMARK_TARGETS)}')


def user_bookmark_create(*, user_id: int, object_id: int, content_type: str) -> UserBookmark:
    model, field = _user_bookmark_target(content_type)

    if not model.objects.filter(id=object_id, active=True).exists():
        raise NotFound(f'{content_type} with id {object_id} does not exist')

    try:
        with transaction.atomic():
            return UserBookmark.objects.create(user_id=user_id, **{f'{field}_id': object_id})

    except IntegrityError:
        raise ValidationError('Already bookmarked')


def user_bookmark_delete(*, user_id: int, object_id: int, content_type: str):
    _, field = _user_bookmark_target(content_type)

    deleted_count = UserBookmark.objects.filter(user_id=user_id, **{f'{field}_id': object_id}).delete()[0]
    if not deleted_count:
        raise NotFound('Bookmark does not exist')
