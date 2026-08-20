"""Промежуточные обработчики запросов."""
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Не пускает дальше, пока не задан собственный пароль.

    Временный пароль знает не только владелец: его видел администратор,
    он мог уйти письмом или в чат. Поэтому до первой смены доступ к данным
    закрыт — открыты только сама смена пароля и выход.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            profile = getattr(user, 'profile', None)
            if profile and profile.must_change_password and self._is_protected(request):
                return redirect('password_change')
        return self.get_response(request)

    @staticmethod
    def _is_protected(request):
        allowed = {
            reverse('password_change'),
            reverse('password_change_done'),
            reverse('logout'),
        }
        path = request.path
        # Админку тоже закрываем, иначе требование обходится через /admin/
        return path not in allowed and not path.startswith('/static/')
