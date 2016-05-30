from django.db import models


class TestDjangoModel(models.Model):
    name = models.CharField(max_length=128)

    # Possible attributes
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    email = models.EmailField(max_length=255)
    employeeID = models.CharField(max_length=128)
