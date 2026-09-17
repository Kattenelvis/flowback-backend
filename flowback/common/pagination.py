from collections import OrderedDict

from rest_framework.pagination import LimitOffsetPagination as _LimitOffsetPagination, LimitOffsetPagination
from rest_framework.response import Response


# Default pagination getter for list views
def get_paginated_response(*,
                           pagination_class = LimitOffsetPagination,
                           serializer_class = None,
                           queryset,
                           request,
                           view):
    paginator = pagination_class()

    page = paginator.paginate_queryset(queryset, request, view=view)

    if serializer_class is None:
        if not hasattr(view, "OutputSerializer"):
            raise ValueError("Paginated response attempted to get OutputSerializer from view, but it does not exist.")

        serializer_class = view.OutputSerializer

    if page is not None:
        serializer = serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    serializer = serializer_class(queryset, many=True)

    return Response(data=serializer.data)


# Default pagination class for list views
class LimitOffsetPagination(_LimitOffsetPagination):
    default_limit = 10
    max_limit = 50

    def get_paginated_data(self, data):
        return OrderedDict([
            ('limit', self.limit),
            ('offset', self.offset),
            ('count', self.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ])

    def get_paginated_response(self, data):
        """
        We redefine this method in order to return `limit` and `offset`.
        This is used by the frontend to construct the pagination itself.
        """
        return Response(OrderedDict([
            ('limit', self.limit),
            ('offset', self.offset),
            ('count', self.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ]))