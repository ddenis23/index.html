from django.http import HttpResponse
from django.urls import path
from django.views.generic import RedirectView

from pontaj.views import people, reports, schedule

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='lunar'), name='home'),
    path('healthz', lambda request: HttpResponse('ok')),
    path('login/', people.login_view, name='login'),
    path('logout/', people.logout_view, name='logout'),
    path('cont/parola/', people.password_change, name='password_change'),

    path('lunar/', schedule.month_view, name='lunar'),
    path('lunar/export/', reports.export_month, name='export_month'),
    path('saptamanal/', schedule.week_view, name='saptamanal'),
    path('saptamanal/export/', reports.export_week, name='export_week'),
    path('pontaj/celula/', schedule.cell, name='cell'),
    path('pontaj/bonus/', schedule.bonus, name='bonus'),

    path('angajati/', people.employee_list, name='employees'),
    path('angajati/nou/', people.employee_form, name='employee_new'),
    path('angajati/<str:pk>/', people.employee_form, name='employee_edit'),
    path('angajati/<str:pk>/sterge/', people.employee_delete, name='employee_delete'),
    path('sectii/', people.section_list, name='sections'),
    path('sectii/<str:pk>/', people.section_list, name='section_edit'),
    path('sectii/<str:pk>/sterge/', people.section_delete, name='section_delete'),
    path('conturi/', people.user_list, name='users'),
    path('conturi/nou/', people.user_form, name='user_new'),
    path('conturi/<str:pk>/', people.user_form, name='user_edit'),

    path('statistici/', reports.stats, name='stats'),
    path('istoric/', reports.history, name='history'),
    path('istoric/backup/', reports.backup, name='backup'),
]
