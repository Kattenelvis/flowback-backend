import django_filters

from flowback.comment.models import Comment


class BaseCommentFilter(django_filters.filterset):
    order_by = django_filters.OrderingFilter(
        fields=(('created_at', 'created_at_asc'),
                ('-created_at', 'created_at_desc'),
                ('score', 'score_asc'),
                ('-score', 'score_desc'))
    )

    class Meta:
        model = Comment
        fields = dict(id=['exact'],
                      author=['exact'],
                      parent=['exact'],
                      score=['gt'])


def comment_list(*, comment_section_id: int, filters=None):
    filters = filters or {}

    if 'parent' not in filters.keys():
        filters['parent'] = None

    qs = Comment.objects.filter(comment_section_id=comment_section_id).all()
    return BaseCommentFilter(filters, qs).qs
