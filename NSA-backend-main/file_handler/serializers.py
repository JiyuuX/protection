
from rest_framework import serializers
from .models import UserProjects

class UserProjectsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProjects
        fields = ['title']

