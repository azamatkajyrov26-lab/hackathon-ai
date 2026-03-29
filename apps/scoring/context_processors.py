def user_role(request):
    """Добавляет роль пользователя в контекст всех шаблонов."""
    if request.user.is_authenticated:
        try:
            return {'user_role': request.user.profile.role}
        except Exception:
            return {'user_role': 'applicant'}
    return {'user_role': ''}
