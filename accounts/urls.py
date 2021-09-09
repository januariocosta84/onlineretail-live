from .import views as core_view
from django.urls import path

app_name ='accounts'
urlpatterns =[
    path('register/', core_view.register, name='register'),
    path('login/', core_view.userlogin, name ='login'),
    path('logout/', core_view.user_logout, name='logout'),
    path('reset/', core_view.reset, name='reset')

]