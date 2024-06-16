from django.urls import path
from .views import line_bot_webhook

urlpatterns = [path('line-bot-webhook/', line_bot_webhook, name='line-bot-webhook')]
