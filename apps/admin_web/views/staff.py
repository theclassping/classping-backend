from ..views_common import *

def staff_detail(request, pk):
    staff = get_object_or_404(
        Staff.objects.select_related("user", "branch__school"),
        pk=pk,
    )
    return render(request, "admin_web/staff/detail.html", {"staff": staff})


def staff_list(request):
    """
    Display all staff members.

    We use select_related() because Staff has ForeignKey/OneToOne
    relationships with Branch and User.
    """

    staffs = (
        Staff.objects
        .select_related(
            "branch",
            "branch__school",
            "user",
        )
        .order_by("first_name", "last_name")
    )

    return render(
        request,
        "admin_web/staff/list.html",
        {
            "staffs": staffs,
        },
    )


