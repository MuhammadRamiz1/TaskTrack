from django.urls import path

from . import views as v

T = "<uuid:task_id>/"

urlpatterns = [
    path("", v.TaskListView.as_view(), name="tasks"),
    path("board/", v.TaskBoardView.as_view(), name="task-board"),
    path("calendar/", v.TaskCalendarView.as_view(), name="task-calendar"),
    path("workload/", v.WorkloadView.as_view(), name="task-workload"),
    path("bulk-assign/", v.BulkAssignView.as_view(), name="task-bulk-assign"),
    path("by-key/<str:key>/", v.TaskByKeyView.as_view(), name="task-by-key"),
    path(T, v.TaskDetailView.as_view(), name="task-detail"),
    path(T + "restore/", v.TaskRestoreView.as_view(), name="task-restore"),
    path(T + "assignees/", v.AssigneesView.as_view(), name="task-assignees"),
    path(T + "assignees/<uuid:user_id>/", v.AssigneeDetailView.as_view(), name="task-assignee-detail"),
    path(T + "reassign/", v.ReassignView.as_view(), name="task-reassign"),
    path(T + "acknowledge/", v.AcknowledgeView.as_view(), name="task-acknowledge"),
    path(T + "transition/", v.TransitionView.as_view(), name="task-transition"),
    path(T + "transitions/", v.AllowedTransitionsView.as_view(), name="task-transitions"),
    path(T + "reopen/", v.ReopenView.as_view(), name="task-reopen"),
    path(T + "escalate/", v.EscalateView.as_view(), name="task-escalate"),
    path(T + "subtasks/", v.SubtasksView.as_view(), name="task-subtasks"),
    path(T + "checklists/", v.ChecklistsView.as_view(), name="task-checklists"),
    path(T + "checklists/<uuid:checklist_id>/", v.ChecklistDetailView.as_view(), name="task-checklist-detail"),
    path(T + "checklists/<uuid:checklist_id>/items/", v.ChecklistItemsView.as_view(), name="task-checklist-items"),
    path(T + "checklist-items/<uuid:item_id>/", v.ChecklistItemDetailView.as_view(), name="task-checklist-item"),
    path(T + "dependencies/", v.DependenciesView.as_view(), name="task-dependencies"),
    path(T + "dependencies/<uuid:dependency_id>/", v.DependencyDetailView.as_view(), name="task-dependency-detail"),
    path(T + "comments/", v.CommentsView.as_view(), name="task-comments"),
    path(T + "comments/<uuid:comment_id>/", v.CommentDetailView.as_view(), name="task-comment-detail"),
    path(T + "attachments/", v.AttachmentsView.as_view(), name="task-attachments"),
    path(T + "attachments/<uuid:attachment_id>/", v.AttachmentDetailView.as_view(), name="task-attachment-detail"),
    path(
        T + "attachments/<uuid:attachment_id>/download/",
        v.AttachmentDownloadView.as_view(),
        name="task-attachment-download",
    ),
    path(T + "activity/", v.ActivityView.as_view(), name="task-activity"),
]
