from django import forms
from .models import Product
from django.contrib.auth import login, authenticate

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Seller, Product, Comment



#---------------Seller user form

class SellerUserForm(forms.ModelForm):
    password =forms.CharField(widget=forms.PasswordInput())
    class Meta:
        model = User

        def get_username(self):
            self.username= self.first_name
            return self.username

        fields =['first_name','last_name','username', 'email', 'password']

        def __init__(self, *args, **kwargs):
            super(SellerUserForm, self).__init__(*args, **kwargs)
            self.fields['username'].required =False


#---------------Seller form
class SellerForm(forms.ModelForm):
    class Meta:
        model = Seller
        fields =('address', 'mobile')


#-------------------Product form

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields=('name', 'product_image', 
                'category','price', 'description',
                'country','item_location','quantity', 'condition'
                )
        #labels ={
        #    'name':'Product Name',
        #    'item_location':'City',
        #    'seller' :'Name'
        #}

    # def __init__(self,*args, **kwargs):
       
    #     super(ProductForm,self).__init__(*args, **kwargs)
    #     #user=User.objects.get(user_id=self.seller)
    #     self.fields['category'].empty_label='Select Category'
    #     self.fields['item_location'].empty_label='Select City'
    #     self.fields['country'].empty_label ='Select Country'
    #     self.fields['quantity'].required = False
     
class CommentForm(forms.ModelForm):
    class Meta:
        model=Comment
        fields='__all__'

 