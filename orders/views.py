from django.db import connections
from django.http import request
from django.http.response import HttpResponse, JsonResponse

from django.shortcuts import redirect, render
from carts.models import CartItem
from greatkart.settings import RAZORPAY_API_KEY, RAZORPAY_API_SECRET_KEY
from .forms import OrderForm
from .models import Order, OrderProduct, Payment
import datetime
from store.models import Product

import razorpay
import json

from django.core.mail import EmailMessage
from django.template.loader import render_to_string
# Create your views here.

def payments(request):
    body = json.loads(request.body)
    order = Order.objects.get(user=request.user,is_ordered=False, order_number=body['orderID'])

    # store transaction inside the payment model
    payment = Payment(
        user = request.user,
        payment_id = body['transID'],
        payment_method = body['payment_method'],
        amount_paid = order.order_total,
        status = body['status'],
    )
    payment.save()
    order.payment = payment
    order.is_ordered = True
    order.status = 'Completed'
    order.save()
    # move the cart items to order product table
    cart_items = CartItem.objects.filter(user= request.user)

    for item in cart_items:
        orderproduct = OrderProduct()
        orderproduct.order_id = order.id
        orderproduct.payment = payment
        orderproduct.user_id = request.user.id
        orderproduct.product_id = item.product_id
        orderproduct.quantity = item.quantity
        orderproduct.product_price = item.product.price
        orderproduct.ordered = True
        orderproduct.save()
        
        cart_item = CartItem.objects.get(id=item.id)
        product_variation = cart_item.variations.all()
        orderproduct = OrderProduct.objects.get(id=orderproduct.id)
        orderproduct.variations.set(product_variation)
        orderproduct.save()

        # Reduce the quantity of the sold products
        product = Product.objects.get(id=item.product_id)
        product.stock -= item.quantity
        product.save()

    #clear cart
    CartItem.objects.filter(user=request.user).delete()


    # send order recieved mail to customer 
    mail_subject = 'Thank you for your order'
    message = render_to_string('orders/order_recieved_email.html',{
        'user': request.user,
        'order':order,
    })
    to_mail = request.user.email
    send_email = EmailMessage(mail_subject, message, to=[to_mail] )
    send_email.send()

    # send order number and transaction id back to sendData mathod via jsonResponse
    data={
        'order_number': order.order_number,
        'transID':payment.payment_id
    }
    return JsonResponse(data)




    return render(request, 'orders/payments.html')


def place_order(request, total = 0, quantity = 0,):
    current_user = request.user
    # if the cart item is less than or equal to 0, then rediect to store page
    cart_items = CartItem.objects.filter(user= current_user)
    cart_count = cart_items.count()
    if cart_count <= 0 :
        return redirect('store')

    grand_total = 0
    tax = 0
    for cart_item in cart_items:
        total += (cart_item.product.price * cart_item.quantity)
        quantity += cart_item.quantity
    tax = (5 * total)/100
    grand_total = total + tax
    
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            # Store all billing information inside Order Table
            data = Order()
            data.user = current_user
            data.first_name = form.cleaned_data['first_name']
            data.last_name = form.cleaned_data['last_name']
            data.phone = form.cleaned_data['phone']
            data.email = form.cleaned_data['email']
            data.address_line1 = form.cleaned_data['address_line1']
            data.pincode = form.cleaned_data['pincode']
            data.country = form.cleaned_data['country']
            data.state = form.cleaned_data['state']
            data.city = form.cleaned_data['city']
            data.order_note = form.cleaned_data['order_note']
            data.order_total = grand_total
            data.tax = tax
            data.ip = request.META.get('REMOTE_ADDR')
            data.save()
            # Generate order number
            yr = int(datetime.date.today().strftime('%Y'))
            dt = int(datetime.date.today().strftime("%d"))
            mt = int(datetime.date.today().strftime('%m'))
            d  = datetime.date(yr,mt,dt)
            current_date = d.strftime("%Y%m%d")

            order_number = current_date + str(data.id)
            data.order_number = order_number
            data.save()

            order = Order.objects.get(user=current_user, is_ordered=False, order_number= order_number)
            total_amount = grand_total * 100
            final_amount = int(total_amount)
            client = razorpay.Client(auth=(RAZORPAY_API_KEY, RAZORPAY_API_SECRET_KEY))
            data = { "amount": final_amount, "currency": "INR", 'payment_capture': 1 }
            payment = client.order.create(data=data)
            payment_id = payment['id']
            
            # retrive customer data to razorpay
            email = form.cleaned_data['email']
            phone = form.cleaned_data['phone']
            name = form.cleaned_data['first_name']

            context= {
                'order' : order,
                'card_items': cart_items,
                'total':total,
                'tax': tax,
                'grand_total':grand_total,
                'api_key':RAZORPAY_API_KEY,
                'order_id':payment_id,
                'email':email,
                'phone':phone,
                'name':name,
            }
            return render(request,'orders/payments.html', context)
           
    else:
        return redirect('checkout')

def order_complete(request):
     order_number = request.GET.get('order_number')
     transID = request.GET.get('payment_id')
     try:
         order = Order.objects.get(order_number=order_number, is_ordered =True)
         ordered_products = OrderProduct.objects.filter(order_id=order.id)

         subtotal =0
         for i in ordered_products:
             subtotal += i.product_price * i.quantity
         
         payment = Payment.objects.get(payment_id= transID)
         context ={
             'order':order,
             'ordered_products':ordered_products,
             'order_number': order.order_number,
             'transID': payment.payment_id,
             'subtotal':subtotal,
         }
         return render(request,'orders/order_complete.html',context)
     except (Payment.DoesNotExist, Order.DoesNotExist):
         return redirect('home')
            
