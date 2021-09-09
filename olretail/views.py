from django.shortcuts import render
from django.views.generic import TemplateView
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.urls import reverse
from django.db.models import Sum
from django.contrib.humanize.templatetags.humanize import intcomma


from .decorators import *
from django.contrib import messages

#-------Import Models
from .models import Product, Seller, Category, Country, City, Comment
#------------import forms
from .forms import SellerUserForm, SellerForm, ProductForm, CommentForm

from django.contrib.auth import authenticate, login, logout
from django.http import HttpResponseRedirect, HttpResponse

from django.contrib.auth.decorators import login_required
#--------User Group

from django.contrib.auth.models import Group

#--------- import Paginator
from django.core.paginator import Paginator

# Create your views here.


class IndexView(TemplateView):
    template_name = 'olretail/index.html'
    paginate_by = 2

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category = self.request.GET.get('category')
        if category == None:
            context['product'] = Product.objects.all().order_by('-price')
        else:
            context['product'] = Product.objects.filter(
                category__title=category)
        context['categories'] = Category.objects.all().order_by('title')
        return context


class DetailsView(TemplateView):
    template_name = 'olretail/details.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug = self.kwargs['slug']
        details = Product.objects.get(slug=slug)
        context['details'] = details
        context['categories'] = Category.objects.all().order_by('title')
        context['comments'] = Comment.objects.all()
        return context


class CategoryView(TemplateView):
    template_name = 'olretail/category.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cat = Category.objects.all()
        context['product'] = Product.objects.all()
        return context


class LoginView(TemplateView):
    template_name = 'olretail/login.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['product'] = Product.objects.all().order_by('-price')
        context['categories'] = Category.objects.all().order_by('title')
        return context


class RegisterView(TemplateView):
    template_name = 'olretail/register.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['product'] = Product.objects.all().order_by('-price')
        context['categories'] = Category.objects.all().order_by('title')
        return context


class ListaView(TemplateView):
    template_name = 'olretail/lista.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['product'] = Product.objects.all().order_by('id')
        context['categories'] = Category.objects.all().order_by('title')
        return context


def searchView(request):
    categories = Category.objects.all().order_by('title')
    if request.method == 'GET':
        search_item = request.GET.get('search')
        print(search_item)
        if search_item:
            product = Product.objects.filter(name__contains=search_item)
            print(product)
            return render(request, 'olretail/search.html', context={'product': product, 'categories': categories})
        else:
            print("No search found")
            return render(request, 'olretail/search.html', {'categories': categories})


@login_required(login_url='/accounts/login/')
@allowed_users(allowed_roles=['Seller'])
def listView(request):
    categories = Category.objects.all().order_by('title')
    product_list = request.user.seller.product_set.all()
    count = len(product_list)
    total_price = request.user.seller.product_set.all().aggregate(Sum('price'))['price__sum']
    total_price = f"$ {intcomma('{:0.2f}'.format(total_price))}"
    print(total_price)
    return render(request, 'olretail/lista.html', context={'product_list': product_list, 'categories': categories, 'count': count, 'total': total_price})


#-----Seller sign form
'''''
def SellersignupView(request):
    categories = Category.objects.all().order_by('title')
    registered = False
    if request.method == 'POST':
        userForm = SellerUserForm(data=request.POST)
        sellerForm = SellerForm(data=request.POST)
        if userForm.is_valid() and sellerForm.is_valid():
            user = userForm.save()
            user.set_password(user.password)
            user.save()
            group = Group.objects.get(name='Seller')
            user.groups.add(group)
            seller = sellerForm.save(commit=False)
            seller.user = user
            seller.save()
            registered = True
            login(request, user)
            messages.success(request, "Registration user successfull.")
            return HttpResponseRedirect('/list')
        messages.error(
            request, "Unsuccessful registration. Invalid Information")

    else:
        userForm = SellerUserForm()
        sellerForm = SellerForm()

    return render(request, 'olretail/signup.html', context={'userForm': userForm, 'sellerForm': sellerForm, 'categories': categories})

'''''
#--------------------Product form


@login_required(login_url='/accounts/login/')
@allowed_users(allowed_roles=['Seller'])
def CreateNewProduct(request):
    cat = Category.objects.all()
    count = Country.objects.all()
    city = City.objects.all()
    successfull = False
    seller_id = request.user.id
    print("seller name", seller_id)
    product_form = ProductForm()
    if request.method == 'POST':
        print("seller within post", seller_id)
        name = request.POST.get('product')
        price = request.POST.get('price')

        image = request.FILES.get('image')
        category = request.POST.get('category')
        country = request.POST.get('country')
        city = request.POST.get('city')
        quantity = request.POST.get('quantity')
        description = request.POST.get('description')
        condition = request.POST.get('condition')
        user_id = request.user.id
        categ = Category.objects.get(id=category)
        countries = Country.objects.get(id=country)
        cities = City.objects.get(id=city)
        seller = Seller.objects.get(user_id=user_id)
        print("user id :", seller, "and")

        product_form = Product.objects.create(name=name,
                                              price=price,
                                              product_image=image,
                                              category=categ,
                                              country=countries,
                                              item_location=cities,
                                              quantity=quantity,
                                              description=description,
                                              seller=seller,
                                              condition=condition,
                                              )
        print("Image product", product_form.product_image)

        #product_form = ProductForm(request.POST,seller, request.FILES)
        #if product_form.is_valid():
        product_form.save()
        successfull = True
        return HttpResponseRedirect('/seller')
    else:
        print('Error in input data', product_form)
    return render(request, 'olretail/products.html',
                  context={'product_form': product_form,
                           'successfull': successfull,
                           'cat': cat,
                           'count': count,
                           'city': city
                           }
                  )
@login_required(login_url='/accounts/login/')
@allowed_users(allowed_roles=['Seller'])
def UpdateProduct(request, slug):
    product = Product.objects.get(slug=slug)
    print(product.name)
    print(product.price)
    form = ProductForm(instance=product)
    print(product)
    return render(request, 'olretail/products_update.html', context={'form':form})
def comment(request):
    form=CommentForm()
    if request.method=='POST':
        form = CommentForm()
    return render(request, 'olretail/comments.html', {'form':form})

'''''
@login_required
def user_logout(request):
    logout(request)
    return HttpResponseRedirect('/')


def user_login(request):
    categories = Category.objects.all().order_by('title')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(username=username, password=password)

        if user:
            if user.is_active:
                login(request, user)
                messages.info(request, f"You are now logged in as {username}.")
                return HttpResponseRedirect('/seller')
            else:
                messages.error(request, 'Account is disabled or not active')
        else:
            messages.error(request, "Invalid username or password.")
    return render(request, 'olretail/login.html', {'categories': categories})
'''''
