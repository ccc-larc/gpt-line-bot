from django.db import models


class UserThread(models.Model):
    id = models.AutoField(primary_key=True)

    line_user_id = models.CharField(max_length=128)
    openai_thread_id = models.CharField(max_length=128)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
