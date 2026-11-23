from django.urls import path

from . import views as v

urlpatterns = [
    path("teams/", v.TeamListView.as_view(), name="org-teams"),
    path("teams/<uuid:team_id>/", v.TeamDetailView.as_view(), name="org-team-detail"),
    path("teams/<uuid:team_id>/members/", v.TeamMembersView.as_view(), name="org-team-members"),
    path(
        "teams/<uuid:team_id>/members/<uuid:user_id>/", v.TeamMemberDetailView.as_view(), name="org-team-member-detail"
    ),
    path("teams/<uuid:team_id>/lead/", v.TeamLeadView.as_view(), name="org-team-lead"),
    path("projects/", v.ProjectListView.as_view(), name="org-projects"),
    path("projects/<uuid:project_id>/", v.ProjectDetailView.as_view(), name="org-project-detail"),
    path("projects/<uuid:project_id>/members/", v.ProjectMembersView.as_view(), name="org-project-members"),
    path(
        "projects/<uuid:project_id>/members/<uuid:user_id>/",
        v.ProjectMemberDetailView.as_view(),
        name="org-project-member-detail",
    ),
    path("directory/", v.DirectoryView.as_view(), name="org-directory"),
]
