from django.conf import settings
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from .models import UserProjects
from .serializers import UserProjectsSerializer
from .models import UserProjects, UserProjectsData, UserProjectShapes, AllLabels, SharedProjects
from users.models import UserAccount  
from django.db import transaction #atomic
from django.shortcuts import get_object_or_404
from rest_framework import status
from urllib.parse import unquote
from django.core.mail import send_mail
from django.conf import settings
import requests
import csv
import os
import json
import random
import re
from django.http import FileResponse
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError
from rest_framework.permissions import IsAuthenticated
import base64
import instaloader
import tempfile


@api_view(['POST'])
def download_project_from_database(request):
    try:
        # Extract projectTitle from the request data
        project_title = request.data.get('projectTitle')
        #print(f"{project_title=}")
        if not project_title:
            return Response({"error": "Project title is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Find the project ID from UserProjects table
        try:
            project = UserProjects.objects.get(title=project_title)
        except UserProjects.DoesNotExist:
            return Response({"error": "Project not found."}, status=status.HTTP_404_NOT_FOUND)

        #print(f"FOUND THE PROJECT ID ")
        # Fetch project data from UserProjectsData table using the project ID
        project_data = UserProjectsData.objects.filter(project_id_id=project.id).values(
            "id", "project_id", "Data_Id", "Label", "Modularity_Class", "Pageranks", 
            "Custom_Filter", "X", "Y", "Size", "Color", "Level1", "Category"
        )
        #print(f"{project_data=}")
        if not project_data:
            return Response({"error": "No data found for the specified project."}, status=status.HTTP_404_NOT_FOUND)

        # respmse
        return Response({"projectTitle": project_title, "data": list(project_data)}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": "An error occurred.", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    


@api_view(['GET'])
def get_subplots(request, project_title):
    #print(f"Received request for project_title: {project_title}")

    # extract the email from req 
    email = request.GET.get('email')
    #print(f"Received email: {email}")

    if not email:
        return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # find user from email
        user = UserAccount.objects.get(email=email)
        #print(f"User found: {user}")
    except UserAccount.DoesNotExist:
        #print(f"User with email {email} not found.")
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

    # in order to find base title of the project, get rid of the _v section 
    base_title = re.sub(r'_v\d+$', '', project_title)  # deeper_v1 -> deeper
    #print(f"Base title extracted: {base_title}")

    # filter to projects for the user 
    projects = UserProjects.objects.filter(owner=user, title__startswith=base_title)
    #print(f"Found {projects.count()} projects with base title '{base_title}'.")

    # add project titles to the list 
    matched_projects = [project.title for project in projects]
    #print(f"Matched projects: {matched_projects}")

    if not matched_projects:
        #print("No matching projects found.")
        return Response({"error": "No matching projects found"}, status=status.HTTP_404_NOT_FOUND)
    
    return Response({"projects": matched_projects}, status=status.HTTP_200_OK)





@api_view(['POST'])
def create_subplot(request):
    try:
        # Get the input data
        project_title = unquote(request.data.get('projectTitle'))
        selection = unquote(request.data.get('selection'))
        email = unquote(request.data.get('email'))
        
        data = request.data.get('data')  
        shapes = request.data.get('shapes') 

        #print(f"{project_title=}")
        #print(f"{selection=}")
        #print(f"{email=}")
        #print(f"{data=}")  # DEBUG
        #print(f"{shapes=}")  # DEBUG

        # Find user by email
        _user = UserAccount.objects.get(email=email)
        _user_id = _user.id
        #print(f"{_user_id=}")  #DEBUG

        # Get existing projects with base project title 
        base_project_title = project_title.split('_')[0]  # Split to get base title 
        existing_projects = UserProjects.objects.filter(title__startswith=base_project_title)
        print(f"{base_project_title=}") #DEBUG
        print(f"{existing_projects=}")  #DEBUG

        # Extract versions from project titles
        version_numbers = []
        print(f"{version_numbers=}")
        for project in existing_projects:
            match = re.match(rf"{base_project_title}_v(\d+)", project.title)
            if match:
                version_numbers.append(int(match.group(1)))

        # Find the next available version number
        version_number = max(version_numbers, default=0) + 1

        # Create the new project title with the correct version number
        new_project_title = f"{base_project_title}_v{version_number}"

        #print(f"{new_project_title=}") #DEBUG PURPOSE

        # Create the new project
        new_project = UserProjects.objects.create(
            title=new_project_title,
            owner=_user
        )

        print(f"{new_project=}")

        # Prepare data for bulk creation
        data_objects = []
        for row in data:
            data_objects.append(
                UserProjectsData(
                    project_id=new_project,
                    Data_Id=row.get('Data_Id'),  
                    Label=row.get('Label', ''),
                    Modularity_Class=row.get('Modularity_Class', ''),
                    Pageranks=row.get('Pageranks', ''),
                    Custom_Filter=row.get('Custom_Filter', ''),
                    X=row.get('X', ''),
                    Y=row.get('Y', ''),
                    Size=row.get('Size', ''),
                    Color=row.get('Color', ''),
                    Level1=row.get('Level1', ''),
                    Category=row.get('Category', None)  # Can be None
                )
            )

        chunksize = 1000  
        for i in range(0, len(data_objects), chunksize):
            UserProjectsData.objects.bulk_create(data_objects[i:i + chunksize])

        # Save shapes to UserProjectShapes
        if shapes:
            shape_objects = []
            for shape in shapes:
                shape_objects.append(
                    UserProjectShapes(
                        project=new_project,
                        user=_user,  
                        shape_data=shape  # Store entire shape as JSON
                    )
                )

            # Bulk create UserProjectShapes
            UserProjectShapes.objects.bulk_create(shape_objects)

        # Save the shared project to SharedProjects 
        SharedProjects(project_title=new_project_title, from_email=email, to_email=email, role='editor').save()

        return Response({"new_project": new_project_title}, status=status.HTTP_201_CREATED)
    
    except Exception as e:
        print(f"Error: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)





from django.http import HttpResponse


@api_view(['POST'])
def download_file(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        project_title = data.get('projectTitle')
        user_email = data.get('userEmail')

        try:

            # Get the project object based on the project title
            project = UserProjects.objects.get(title=project_title)
            print(f"{project.id=}")

            # Get the associated data from UserProjectsData for this project
            project_data = UserProjectsData.objects.filter(project_id=project.id)
            print(f"{project_data[0:3]=}")
            # If there is no data found for the project
            if not project_data.exists():
                return JsonResponse({'error': 'No data found for the given project'}, status=404)

            # Create a CSV response with the project data
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{project_title}.csv"'

            # Create a CSV writer
            writer = csv.writer(response)
            
            # headers
            writer.writerow(['Id', 'Label', 'Modularity_Class', 'Pageranks', 'Custom_Filter', 'X', 'Y', 'Size', 'Color'])

            # Write each row of project data
            for item in project_data:
                writer.writerow([item.Data_Id, item.Label, item.Modularity_Class, item.Pageranks, item.Custom_Filter, item.X, item.Y, item.Size, item.Color])

            return response

        except UserProjects.DoesNotExist:
            return JsonResponse({'error': 'Project not found'}, status=404)
        except ObjectDoesNotExist:
            return JsonResponse({'error': 'Data not found for the given project'}, status=404)

    return JsonResponse({'error': 'Invalid request method'}, status=405)





def send_email(subject, message, html_message, to_email):
    from_email = settings.EMAIL_HOST_USER
    email = EmailMultiAlternatives(subject, message, from_email, [to_email])
    email.attach_alternative(html_message, "text/html")  # Attach HTML version
    email.send()


@api_view(['POST'])
def user_role(request):
    email = request.data.get('email', '')
    decoded_email = unquote(email)
    project_title = request.data.get('projectTitle', '')
    decoded_project_title = unquote(project_title)

    # Query for the shared project
    data1 = SharedProjects.objects.filter(from_email=decoded_email, project_title=decoded_project_title)
    data2 = SharedProjects.objects.filter(to_email=decoded_email, project_title=decoded_project_title)

    if not data1.exists():
        print("doesn't exist-1")

    if not data2.exists():
        print("doesn't exist-2")
    #print(f"{data1=}")
    #print(f"{data2=}")
    if data1.exists():
        x1 = data1.first()
        #print(f"{x1=}")
        if decoded_email == x1.from_email:
            response_data = {'role': 'editor'}
            return JsonResponse(response_data, safe=False, status=200)

    if data2.exists():
        x2 = data2.first()
        #print(f"{x2=}")
        if decoded_email == x2.to_email:
            response_data = {'role': str(x2.role)}
            return JsonResponse(response_data, safe=False, status=200)

    # Default response if neither condition matches
    return JsonResponse({'error': 'No valid role found'}, safe=False, status=404)
    
    
    

@api_view(['POST'])
def update_role(request):
    try:
        user_email =  unquote(request.data.get('email'))
        to_email= unquote(request.data.get('to_email'))
        project_title =  unquote(request.data.get('project_title'))
        new_role =  unquote(request.data.get('role'))

        #print(f"{user_email=}")
        #print(f"{project_title=}")
        #print(f"{new_role=}")
        #print(f"{to_email=}")
        if not project_title or not new_role:
            return JsonResponse({'error': 'Project title and role are required'}, status=400)

        # Find the shared project based on project title and the user who shared it
        shared_project = SharedProjects.objects.filter(
            project_title=project_title,
            from_email=user_email,
            to_email=to_email
        ).first()

        if not shared_project:
            return JsonResponse({'error': 'Project not found or you do not have permission to update this project'}, status=404)

        # Update the role
        shared_project.role = new_role
        shared_project.save()

        print(f"{shared_project.role=}")

        return JsonResponse({'message': 'Role updated successfully'}, status=200)

    except Exception as e:
        print(f"An error occurred: {e}")
        return JsonResponse({'error': 'An error occurred while updating the role'}, status=500)




@api_view(['GET'])
def shared_projects_withme(request):
    try:
        # extract the user's email
        email = request.user.email
        #print(f"User email: {email}")

        # filter the projects that shared with the user 
        shared_data = SharedProjects.objects.filter(to_email=email)

        # if there is no shared projects ... 
        if not shared_data.exists():
            return JsonResponse({'error': 'No projects found'}, status=404)

        # create the response data
        response_data = [
            {
                'project_title': str(item.project_title),
                'shared_from': str(item.from_email),
                'role': str(item.role),
            }
            for item in shared_data if item.from_email != email  # filter
        ]

        # if after filter, if it is empty.. 
        if not response_data:
            return JsonResponse({'error': 'No relevant projects found'}, status=404)

        #print(response_data)
        return JsonResponse(response_data, status=200, safe=False)

    except Exception as e:
        #print(f"An error occurred: {e}")
        return JsonResponse({'error': 'An error occurred while fetching the projects'}, status=500)



@api_view(['GET'])
def shared_projects(request):
    try:
        email = request.user.email
        #print(f"User email: {email}")
        
        shared_data = SharedProjects.objects.filter(from_email=email)

        if not shared_data.exists():
            return JsonResponse({'error': 'No projects found'}, status=404)

        response_data = []
        for i in shared_data:
            #print(i)
            response_data.append({
                'project_title': str(i.project_title),
                'shared_from': str(i.to_email),
                'role': str(i.role),
            })

        for item in response_data:
            if item['shared_from'] == email:
                response_data.remove(item) 

        #print(response_data)
        return JsonResponse(response_data, status=200, safe=False)

    except Exception as e:
        print(f"An error occurred: {e}")
        return JsonResponse({'error': 'An error occurred while fetching the projects'}, status=500)





@api_view(['POST'])
def share_project(request):
    try:
        # Request'ten gerekli verileri al
        project_title = unquote(request.data.get('projectTitle', ''))
        from_email = unquote(request.data.get('from_email', ''))
        to_email = unquote(request.data.get('to_email', ''))
        role = request.data.get('role', '').lower()

        #print(f"{project_title=}")
        #print(f"{from_email=}")
        #print(f"{to_email=}")
        #print(f"{role=}")

        # SharedProjects modeline yeni bir kayıt ekle
        SharedProjects.objects.create(project_title=project_title, from_email=from_email, to_email=to_email, role=role)

        # FROM VERCEL-TAKING LOGO
        logo_url = "https://nsa.deeper.la/deeper-logo.png"

        # HTML message
        html_message = f"""
        <html>
            <head>
                <style>
                    body {{
                        font-family: 'Arial', sans-serif;
                        margin: 0;
                        padding: 0;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        height: 100vh;
                        background-color: #f0f4f8;
                    }}
                    .container {{
                        text-align: center;
                        background: #ffffff;
                        padding: 30px;
                        border-radius: 10px;
                        box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.1);
                        max-width: 400px;
                        width: 100%;
                    }}
                    h1 {{
                        color: #333333;
                        font-size: 22px;
                        margin-bottom: 10px;
                    }}
                    p {{
                        font-size: 16px;
                        color: #555555;
                        margin-bottom: 20px;
                    }}
                    .button {{
                        display: inline-block;
                        padding: 10px 25px;
                        background-color: #007bff;
                        color: white;
                        font-size: 16px;
                        text-align: center;
                        text-decoration: none;
                        border-radius: 5px;
                        transition: all 0.3s ease;
                    }}
                    .button:hover {{
                        background-color: #0056b3;
                    }}
                    .logo {{
                        max-width: 150px;
                        margin-bottom: 20px;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <img src="{logo_url}" alt="Company Logo" class="logo">
                    <h1>New Project</h1>
                    <p>You have been assigned a new project titled <strong>{project_title}</strong>.</p>
                    <p>Click the button below to view the project:</p>
                    <a href="https://nsa.deeper.la/shared-projects-all" class="button">View Project</a>
                </div>
            </body>
        </html>
        """

        # Send Email
        send_email(
            subject='Notification - New Project',
            message='Deeper',
            html_message=html_message,
            to_email=to_email
        )

        return JsonResponse("Project shared successfully", safe=False, status=status.HTTP_200_OK)
    except UserProjects.DoesNotExist:
        return JsonResponse("Project not found", safe=False, status=status.HTTP_404_NOT_FOUND)
    except UserAccount.DoesNotExist:
        return JsonResponse("User not found", safe=False, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        print(f"Error: {str(e)}")
        return JsonResponse("An error occurred", safe=False, status=status.HTTP_500_INTERNAL_SERVER_ERROR)






@api_view(['POST'])
def search_label(request):
    label = request.data.get('label', '').lower()
    email = request.data.get('email', '')
    decoded_email = unquote(email)
    project_title= request.data.get('projectTitle', '')
    decoded_project_title= unquote(project_title)

    # Find user by email then id
    _user = UserAccount.objects.get(email=decoded_email)
    _user_id = _user.id

    # Find project by title
    _project = UserProjects.objects.get(title=decoded_project_title)
    _project_id = _project.id

    if not label:
        return JsonResponse({'message': 'Label is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Look it up for data in database from AllLabels Table
    item = AllLabels.objects.filter(label__iexact=label).first()
    if item:
        item_id = item.data_id
        item_label = item.label
    
        # update the UserProjectsData where the same id exists but the label is empty
        try:
            project_data = UserProjectsData.objects.filter(project_id=_project_id, Data_Id=item_id).first()
            
            if project_data:
                # Update the label field
                project_data.Label = item_label
                project_data.Custom_Filter=True
                project_data.save()
                
                # Return the updated project data
                updated_data = {
                    'Data_Id': project_data.Data_Id,
                    'Label': project_data.Label,
                    'X':project_data.X,
                    'Y':project_data.Y,
                    'Pageranks':project_data.Pageranks,
                    'Custom_Filter':project_data.Custom_Filter,
                    'Size':project_data.Size,
                    'Color':project_data.Color,
                    'Modularity_Class':project_data.Modularity_Class,
                    'Category':project_data.Category,
                }
                
                return JsonResponse({
                    'message': f'The Label does not exist in plot but found in our database, id = {item_id}. Label updated in UserProjectsData.',
                    'updated_data': updated_data
                }, status=status.HTTP_200_OK)
            else:
                return JsonResponse({
                    'message': 'No matching UserProjectsData found to update.'
                }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            print("Error updating UserProjectsData:", str(e))
        return JsonResponse({'message': f'The Label does not exist in plot but found in our database, id = {item_id}'}, status=status.HTTP_200_OK)

    # IF LABEL doesn't exist on the table, then try Instagram
    try:
        username = label
        user_url = f"https://www.instagram.com/{username}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(user_url, headers=headers)
        
        if response.status_code == 429:  # Too Many Requests
            return JsonResponse({
                'success': False,
                'error': 'Rate limit exceeded. Please try again later.'
            }, status=429)
        
        if response.status_code != 200:
            return JsonResponse({
                'success': False,
                'error': f'Failed to fetch user data: {response.status_code}'
            }, status=response.status_code)

        html_content = response.text
        
        # User ID'yi bul
        id_match = re.search(r'"user_id":"(\d+)"', html_content) or re.search(r'"id":"(\d+)"', html_content)
        if not id_match:
            return JsonResponse({
                'success': False,
                'error': 'User not found'
            }, status=404)
        
        user_id = id_match.group(1)
        
        # Instaloader ile profil resmini al
        L = instaloader.Instaloader()
        
        # Geçici bir dosya oluştur
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            # Profil resmini indir
            profile = instaloader.Profile.from_username(L.context, username)
            # Profil resmini direkt URL'den indir
            profile_pic_response = requests.get(profile.profile_pic_url)
            with open(temp_path, 'wb') as f:
                f.write(profile_pic_response.content)
            
            # Resmi base64'e çevir
            with open(temp_path, 'rb') as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            profile_pic = f"data:image/jpeg;base64,{encoded_string}"
            
            return JsonResponse({
                'success': True,
                'username': username,
                'userId': user_id,
                'profilePic': profile_pic
            })

        except Exception as e:
            print(f"Instaloader error: {str(e)}")
            # Hata durumunda UI Avatars'a geri dön
            profile_pic = f"https://ui-avatars.com/api/?name={username}&background=random&size=200"
            
            return JsonResponse({
                'success': False,
                'error': 'Instaloader error occurred',
                'profilePic': profile_pic
            }, status=500)

    except requests.exceptions.RequestException as e:
        print(f"Network error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Network error occurred'
        }, status=500)
    except Exception as e:
        print(f"Error in Instagram search: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)







import psutil
from itertools import islice

@api_view(['POST'])
def save_shapes_view(request, project_title):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        # json data
        #data = json.loads(request.body)
        #print(f"{data=}")
        # Fetch project and owner
        project = UserProjects.objects.get(title=project_title)
        project_owner = UserAccount.objects.get(email=project.owner)

        # Start atomic transaction
        with transaction.atomic():
            # Clear existing data for the project
            UserProjectsData.objects.filter(project_id=project.id).delete()
            UserProjectShapes.objects.filter(project_id=project.id, user_id=project_owner.id).delete()

            # dynamically calculate chunk size based on available memory
            def get_dynamic_chunk_size():
                mem = psutil.virtual_memory()
                print(f"{mem=}")
                # Use 10% of available memory for a chunk, with a fallback minimum size
                max_chunk_size = max(100, int((mem.available / 10) / 100))  # Scale by record size 
                print(f"{max_chunk_size=}")
                print(f"min_chunk_size={min(5000, max_chunk_size) }")
                return min(5000, max_chunk_size)  # Cap chunk size at 5000

            # Process and save nodes in chunks directly from data.get - I didn't store the data in a local variable as mush as I can in order to reduce RAM usage
            def node_generator():
                for node in json.loads(request.body).get('nodeData', []):  # Directly access 'nodeData'- I didn't store the data in a local variable as mush as I can in order to reduce RAM usage
                    if 'X' in node and 'Y' in node:  # check whether mandatory keys exist or not
                        yield UserProjectsData(
                            project_id=project,
                            Data_Id=node.get('Data_Id', ''),
                            Label=node.get('Label', ''),
                            Modularity_Class=node.get('Modularity_Class', ''),
                            Custom_Filter=node.get('Custom_Filter', ''),
                            Pageranks=node.get('Pageranks', ''),
                            X=node['X'],
                            Y=node['Y'],
                            Size=node.get('Size', ''),
                            Color=node.get('Color', ''),
                            Level1=node.get('Level1', ''),
                            Category=node.get('Category', None),
                        )

            node_iterator = node_generator()
            while True:
                dynamic_chunk_size = get_dynamic_chunk_size()
                print(f"{dynamic_chunk_size=}")
                chunk = list(islice(node_iterator, dynamic_chunk_size))
                #print(f"{chunk=}")
                if not chunk:
                    break
                UserProjectsData.objects.bulk_create(chunk)

            # Process and save shapes in chunks directly from data.get
            def shape_generator():
                for shape in json.loads(request.body).get('shapes', []):  # Directly access 'shapes' in order to reduce RAM usage
                    yield UserProjectShapes(
                        project=project,
                        user=project_owner,
                        shape_data=shape
                    )

            shape_iterator = shape_generator()
            while True:
                dynamic_chunk_size = get_dynamic_chunk_size()
                chunk = list(islice(shape_iterator, dynamic_chunk_size)) # actually we storing the data in here, but it is small-not entire JSON data.
                if not chunk:
                    break
                UserProjectShapes.objects.bulk_create(chunk)

        return JsonResponse({'message': 'Shapes and nodes saved successfully'}, status=200)

    except UserAccount.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

    except UserProjects.DoesNotExist:
        return JsonResponse({'error': 'Project not found'}, status=404)

    except IntegrityError as e:
        return JsonResponse({'error': f'Database Integrity Error: {str(e)}'}, status=400)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)





    




@api_view(['GET'])
def load_shapes(request, project_title):
    if request.method == 'GET':
        try:
            # Get the URL-encoded email and decode it
            user_email = unquote(request.GET.get('userEmail', ''))
            user = get_object_or_404(UserAccount, email=user_email)

            project = get_object_or_404(UserProjects, title=project_title)

            shapes = UserProjectShapes.objects.filter(project=project)
            shapes_data = [shape.shape_data for shape in shapes]

            response_data = {
                'shapes': shapes_data,
            }
            #print(f"{response_data=}")
            return JsonResponse(response_data, safe=False)

        except UserAccount.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)

        except UserProjects.DoesNotExist:
            return JsonResponse({'error': 'Project not found'}, status=404)

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    else:
        return JsonResponse({'error': 'Only GET method is allowed'}, status=405)





def get_csrf_token_view(request):
    csrf_token = get_token(request)
    return JsonResponse({'csrfToken': csrf_token})





import tempfile
@method_decorator(csrf_exempt, name='dispatch')
class FileUploadView(View):
    def post(self, request):
        # Check if 'file' and 'projectTitle' are present in request
        if 'file' not in request.FILES or 'projectTitle' not in request.POST:
            return JsonResponse({'error': 'File or project title missing'}, status=400)

        uploaded_file = request.FILES['file']
        project_title = request.POST.get('projectTitle', '').strip()
        user_email = request.POST.get('userEmail', '').strip()

        if not project_title:
            return JsonResponse({'error': 'Project title cannot be empty'}, status=400)

        try:
            user = UserAccount.objects.get(email=user_email)
        except UserAccount.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)

        # Save the uploaded file temporarily on disk
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as temp_file:
            for chunk in uploaded_file.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name

        # Process the temporary file
        try:
            with open(temp_file_path, 'r', encoding='utf-8-sig') as csv_file:
                csv_reader = csv.DictReader(csv_file)
                headers = csv_reader.fieldnames

                required_columns = ['Id', 'Label', 'Modularity_Class', 'Pageranks', 'Filter', 'X', 'Y', 'Size', 'Color', 'Level1']
                if not all(col in headers for col in required_columns):
                    return JsonResponse({'error': 'CSV file does not contain the required columns'}, status=400)

                # Create or get the project object
                project_obj, created = UserProjects.objects.get_or_create(title=project_title, owner=user)

                # Read and save data in chunks to reduce memory usage
                chunk_size = 1000
                user_project_data_list = []

                for row in csv_reader:
                    user_project_data_list.append(UserProjectsData(
                        project_id=project_obj,
                        Data_Id=row['Id'],
                        Label=row['Label'],
                        Modularity_Class=row['Modularity_Class'],
                        Pageranks=row['Pageranks'],
                        Custom_Filter=row['Filter'],
                        X=row['X'],
                        Y=row['Y'],
                        Size=row['Size'],
                        Color=row['Color'],
                        Level1=row['Level1']
                    ))

                    if len(user_project_data_list) >= chunk_size:
                        with transaction.atomic():
                            UserProjectsData.objects.bulk_create(user_project_data_list)
                        user_project_data_list.clear()

                # Save remaining records
                if user_project_data_list:
                    with transaction.atomic():
                        UserProjectsData.objects.bulk_create(user_project_data_list)

                # Create shared project entry
                SharedProjects(
                    project_title=project_title,
                    from_email=user_email,
                    to_email=user_email,
                    role='editor'
                ).save()

            return JsonResponse({'message': 'File uploaded and processed successfully'}, status=200)

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

        finally:
            # we have to make sure the temporary file is deleted
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)






@api_view(['GET'])
def user_projects(request):
    user = request.user

    if user.is_authenticated:  # is user auth check ???
        user_email = user
        projects = UserProjects.objects.filter(owner=user_email)
        project_titles = [project.title for project in projects]
        #print("calisti")
        return Response({'projects': project_titles})
    else:
        return Response({'error': 'User is not authenticated.'}, status=401)





#@api_view(['GET'])
@csrf_exempt
def user_project_data(request, project_title):
    try:
        project = get_object_or_404(UserProjects, title=project_title)

        # Exclude if Label is empty 
        data = UserProjectsData.objects.filter(project_id=project.id).exclude(
            Label='',       # Exclude empty labels
        ).exclude(
            Label__isnull=True  # Exclude NULL labels
        ).values(
            'Data_Id', 
            'Label', 
            'X', 
            'Y', 
            'Size', 
            'Color', 
            'Level1', 
            'Pageranks', 
            'Custom_Filter', 
            'Modularity_Class', 
            'Category'
        )

        return JsonResponse(list(data), status=200, safe=False)
    
    except UserProjects.DoesNotExist:
        return JsonResponse({'error': 'Project not found'}, status=404)
    except UserProjectsData.DoesNotExist:
        return JsonResponse({'error': 'Project data not found'}, status=404)





@csrf_exempt
def user_project_delete(request, project_title):
    # Only handle DELETE request
    if request.method == 'DELETE':
        project = get_object_or_404(UserProjects, title=project_title)
        #print(project)
        project.delete()
        
        # Delete associated shared projects
        shared = SharedProjects.objects.filter(project_title=project_title)
        #print(shared)
        for i in shared:
            #print(i)
            i.delete()
        
        return JsonResponse({'message': 'Project and associated data deleted successfully.'}, status=status.HTTP_200_OK)

    return JsonResponse({'error': 'Invalid request method.'}, status=status.HTTP_400_BAD_REQUEST)




@csrf_exempt
def check_project_title(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            project_title = data.get('projectTitle')
            user_email = data.get('userEmail')

            # check mechanism project title 
            exists = UserProjects.objects.filter(title=project_title).exists()
            return JsonResponse({'exists': exists})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=400)
   
   

@api_view(['POST'])
def create_file_project(request):
    try:
        data = request.data
        title = data.get('title')
        users = data.get('users', [])
        
        if not title:
            return JsonResponse({'success': False, 'error': 'Title is required'}, status=400)
        
        if not users:
            return JsonResponse({'success': False, 'error': 'At least one user is required'}, status=400)
        
        # Yeni proje oluştur
        project = UserProjects.objects.create(
            title=title,
            owner=request.user
        )

        # Instagram kullanıcılarını AllLabels tablosuna ekle
        for user in users:
            AllLabels.objects.get_or_create(
                data_id=user['userId'],
                label=user['username']
            )

        # Projeyi paylaşılanlar listesine ekle
        SharedProjects.objects.create(
            project_title=title,
            from_email=request.user.email,
            to_email=request.user.email,
            role='editor'
        )

        print(f"New Project Created:")
        print(f"Title: {title}")
        print("Instagram Users:")
        for user in users:
            print(f"- Username: {user['username']}, User ID: {user['userId']}")
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        print(f"Error creating project: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
   
   

@api_view(['POST'])
def get_instagram_user_info(request):
    try:
        username = request.data.get('username')
        if not username:
            return JsonResponse({'success': False, 'error': 'Username is required'}, status=400)

        # Instagram web sayfasından veri çekme
        user_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'X-IG-App-ID': '936619743392459',
            'X-Requested-With': 'XMLHttpRequest'
        }
        
        response = requests.get(user_url, headers=headers)
        
        if response.status_code == 429:  # Too Many Requests
            return JsonResponse({
                'success': False,
                'error': 'Rate limit exceeded. Please try again later.'
            }, status=429)
        
        if response.status_code != 200:
            return JsonResponse({
                'success': False,
                'error': f'Failed to fetch user data: {response.status_code}'
            }, status=response.status_code)

        data = response.json()
        if 'data' in data and 'user' in data['data']:
            user_data = data['data']['user']
            user_id = user_data['id']
            
            # Instaloader ile profil resmini al
            L = instaloader.Instaloader()
            
            # Geçici bir dosya oluştur
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                temp_path = temp_file.name
            
            try:
                # Profil resmini indir
                profile = instaloader.Profile.from_username(L.context, username)
                # Profil resmini direkt URL'den indir
                profile_pic_response = requests.get(profile.profile_pic_url)
                with open(temp_path, 'wb') as f:
                    f.write(profile_pic_response.content)
                
                # Resmi base64'e çevir
                with open(temp_path, 'rb') as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                profile_pic = f"data:image/jpeg;base64,{encoded_string}"
                
            except Exception as e:
                print(f"Instaloader error: {str(e)}")
                # Hata durumunda UI Avatars'a geri dön
                profile_pic = f"https://ui-avatars.com/api/?name={username}&background=random&size=200"
            
            finally:
                # Geçici dosyayı sil
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                
            return JsonResponse({
                'success': True,
                'username': username,
                'userId': user_id,
                'profilePic': profile_pic
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'User not found'
            }, status=404)

    except requests.exceptions.RequestException as e:
        return JsonResponse({
            'success': False,
            'error': 'Network error occurred'
        }, status=500)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)







