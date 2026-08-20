from django.urls import path

from . import views

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),

    path('operations/', views.TransactionListView.as_view(), name='transaction_list'),
    path('operations/add/', views.TransactionCreateView.as_view(), name='transaction_add'),
    path('operations/<int:pk>/edit/', views.TransactionUpdateView.as_view(), name='transaction_edit'),
    path('operations/<int:pk>/delete/', views.TransactionDeleteView.as_view(), name='transaction_delete'),

    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/add/', views.CategoryCreateView.as_view(), name='category_add'),
    path('categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='category_edit'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),
]
