from django.shortcuts import render
from django.contrib.auth.models import User

from olretail.models import Seller, Category
from django.contrib.auth import authenticate, login, logout

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.http import HttpResponseRedirect, HttpResponse
from django.contrib.auth.models import Group


def register(request):
    categories = Category.objects.all().order_by('title')
    message=''
    error=False
    if request.method=='POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        first_name = request.POST.get('first')
        last_name = request.POST.get('last')
        mobile = request.POST.get('mobile')
        address = request.POST.get('address')

        if User.objects.filter(username=username).exists():
            message='Username already exist'
            error=True
            print("Username already exist")
            return HttpResponse(message)
        else:
            if  User.objects.filter(email=email).exists():
                message='Email is already exist'
                error=True
                print("Email already exist")
                return HttpResponse(message)
            else:
                user = User.objects.create_user(username=username, email=email,password=password,first_name=first_name)
                user.save()
                group = Group.objects.get(name='Seller')
                user.groups.add(group)
                seller = Seller.objects.create(user=user, address=address, mobile=mobile)
                seller.save()
                if user is not None:
                    login(request, user)
                    return HttpResponseRedirect('/seller')
    else:
        return render(request, 'accounts/register.html', {'message':message, 'error':error,'categories':categories})


def userlogin(request):
    categories = Category.objects.all().order_by('title')
    if request.method=='POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)
            return HttpResponseRedirect('/seller')
    return render(request, 'accounts/login.html', {'categories':categories})

  
def reset(request):
    categories = Category.objects.all().order_by('title')
    return render(request, 'accounts/reset.html', {'categories':categories})


@login_required
def user_logout(request):
    logout(request)
    return HttpResponseRedirect('/')
