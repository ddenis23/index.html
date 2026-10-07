from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from pontaj.views import people, reports, schedule

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='lunar'), name='home'),
    path('login/', auth_views.LoginView.as_view(template_name='pontaj/login.html',
                                                redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('cont/parola/', people.PasswordChange.as_view(), name='password_change'),

    path('lunar/', schedule.month_view, name='lunar'),
    path('lunar/export/', reports.export_month, name='export_month'),
    path('saptamanal/', schedule.week_view, name='saptamanal'),
    path('saptamanal/export/', reports.export_week, name='export_week'),
    path('pontaj/celula/', schedule.cell, name='cell'),
    path('pontaj/bonus/', schedule.bonus, name='bonus'),

    path('angajati/', people.employee_list, name='employees'),
    path('angajati/nou/', people.employee_form, name='employee_new'),
    path('angajati/<int:pk>/', people.employee_form, name='employee_edit'),
    path('angajati/<int:pk>/sterge/', people.employee_delete, name='employee_delete'),
    path('sectii/', people.section_list, name='sections'),
    path('sectii/<int:pk>/', people.section_list, name='section_edit'),
    path('sectii/<int:pk>/sterge/', people.section_delete, name='section_delete'),
    path('conturi/', people.user_list, name='users'),
    path('conturi/nou/', people.user_form, name='user_new'),
    path('conturi/<int:pk>/', people.user_form, name='user_edit'),

    path('statistici/', reports.stats, name='stats'),
    path('istoric/', reports.history, name='history'),
]
