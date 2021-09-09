
from .views import (
    IndexView, LoginView, DetailsView, ListaView,CategoryView
) 
from .import views as core_view
from django.urls import path

app_name='olretail'

urlpatterns =[
    path('', IndexView.as_view(), name='index' ),
    path('login/', LoginView.as_view(), name ='login'),
    path('seller/create-product/', core_view.CreateNewProduct, name='create_product'),
    path('seller/update-product/<slug:slug>', core_view.UpdateProduct, name='update_product'),
   # path('create_product/<int:id>', core_view.CreateNewProduct, name='create'),
    path('details/<slug:slug>/', DetailsView.as_view(), name='details'),
    path('seller/', core_view.listView, name='list'),
    #path('user_login/', core_view.user_login, name='user_login'),
    #path('userlogout/', core_view.user_logout, name='log_out'),
    path('category/<int:id>', CategoryView.as_view(), name='category' ),
    path('search/', core_view.searchView, name='search'),
    path('details/<slug:slug>', core_view.searchView, name='details-search'),
    path('comments/', core_view.comment, name='add-comments'),
]