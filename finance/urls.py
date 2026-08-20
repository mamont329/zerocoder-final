from django.urls import path

from . import views

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),

    path('analytics/', views.AnalyticsView.as_view(), name='analytics'),
    path('analytics/reports/save/', views.SavedReportCreateView.as_view(), name='report_save'),
    path('analytics/reports/<int:pk>/delete/', views.SavedReportDeleteView.as_view(), name='report_delete'),

    path('operations/', views.TransactionListView.as_view(), name='transaction_list'),
    path('operations/add/', views.TransactionCreateView.as_view(), name='transaction_add'),
    path('operations/<int:pk>/edit/', views.TransactionUpdateView.as_view(), name='transaction_edit'),
    path('operations/<int:pk>/delete/', views.TransactionDeleteView.as_view(), name='transaction_delete'),

    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/telegram/unlink/', views.TelegramUnlinkView.as_view(), name='telegram_unlink'),
    path('profile/account/', views.AccountUpdateView.as_view(), name='account_edit'),
    path('profile/deactivate/', views.AccountDeactivateView.as_view(), name='account_deactivate'),

    path('maintenance/', views.MaintenanceView.as_view(), name='maintenance'),

    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/add/', views.UserCreateView.as_view(), name='user_add'),
    path('users/<int:pk>/toggle/', views.UserToggleActiveView.as_view(), name='user_toggle'),
    path('users/<int:pk>/reset-password/', views.UserResetPasswordView.as_view(), name='user_reset_password'),
    path('users/credentials/', views.UserCredentialsView.as_view(), name='user_credentials'),
    path('users/<int:pk>/delete/', views.UserDeleteView.as_view(), name='user_delete'),

    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/add/', views.CategoryCreateView.as_view(), name='category_add'),
    path('categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='category_edit'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),
]
