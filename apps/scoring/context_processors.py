def user_role(request):
    """Добавляет роль пользователя и счётчик уведомлений в контекст всех шаблонов."""
    if request.user.is_authenticated:
        try:
            role = request.user.profile.role
        except Exception:
            role = 'applicant'
        from apps.scoring.models import Notification
        unread = Notification.objects.filter(user=request.user, is_read=False).count()
        return {'user_role': role, 'unread_notifications': unread}
    return {'user_role': '', 'unread_notifications': 0}
