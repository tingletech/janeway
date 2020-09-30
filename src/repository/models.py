__copyright__ = "Copyright 2017 Birkbeck, University of London"
__author__ = "Martin Paul Eve & Andy Byers"
__license__ = "AGPL v3"
__maintainer__ = "Birkbeck Centre for Technology and Publishing"

import os
import uuid
from dateutil import parser as dateparser

from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from django.dispatch import receiver
from django.shortcuts import reverse
from django.http.request import split_domain_port

from core.file_system import JanewayFileSystemStorage
from core import model_utils, files
from utils import logic
from repository import install
from utils.function_cache import cache


STAGE_PREPRINT_UNSUBMITTED = 'preprint_unsubmitted'
STAGE_PREPRINT_REVIEW = 'preprint_review'
STAGE_PREPRINT_PUBLISHED = 'preprint_published'
STAGE_PREPRINT_REJECTED = 'preprint_rejected'

SUBMITTED_STAGES = {
    STAGE_PREPRINT_REVIEW,
    STAGE_PREPRINT_PUBLISHED,
    STAGE_PREPRINT_REJECTED
}


def html_input_types():
    return (
        ('text', 'Text'),
        ('select', 'Dropdown'),
        ('checkbox', 'Checkbox'),
        ('number', 'Number'),
        ('date', 'Date'),
    )


def width_choices():
    return (
        (3, '3'),
        (6, '6'),
        (9, '9'),
        (12, '12'),
    )


fs_path = os.path.join('files/')
preprint_file_store = JanewayFileSystemStorage(location=fs_path)

media_path = settings.MEDIA_ROOT  # TODO: @mauro to make this relative?
preprint_media_store = JanewayFileSystemStorage(location=media_path)


def preprint_file_upload(instance, filename):
    try:
        uuid_filename = str(uuid.uuid4()) + '.' + str(filename.split('.')[1])
    except IndexError:
        uuid_filename = str(uuid.uuid4())

    path = os.path.join('repos', str(instance.preprint.pk), uuid_filename)
    instance.original_filename = filename
    return path


def repo_media_upload(instance, filename):
    try:
        filename = str(uuid.uuid4()) + '.' + str(filename.split('.')[1])
    except IndexError:
        filename = str(uuid.uuid4())

    path = "repos/{0}/".format(instance.pk)
    return os.path.join(path, filename)


class Repository(model_utils.AbstractSiteModel):
    press = models.ForeignKey('press.Press')
    name = models.CharField(max_length=255)
    short_name = models.CharField(
        max_length=15,
        help_text='Shortened version of the name eg. olh. Max 15 chars.'
    )
    object_name = models.CharField(
        max_length=255,
        help_text='eg. preprint or article',
    )
    object_name_plural = models.CharField(
        max_length=255,
        help_text='eg. preprints or articles',
    )
    managers = models.ManyToManyField('core.Account', blank=True)
    logo = models.ImageField(
        blank=True,
        null=True,
        storage=preprint_media_store,
        upload_to=repo_media_upload,
    )
    favicon = models.ImageField(
        blank=True,
        null=True,
        storage=preprint_media_store,
        upload_to=repo_media_upload,
    )
    hero_background = models.ImageField(
        blank=True,
        null=True,
        storage=preprint_media_store,
        upload_to=repo_media_upload,
    )
    publisher = models.CharField(
        max_length=255,
        help_text=_('Used for outputs including DC and Citation metadata'),
    )
    custom_js_code = models.TextField(
        blank=True,
        null=True,
        help_text=_('The contents of this field are output into the JS area'
                    'at the foot of every Repository page.')
    )
    live = models.BooleanField(
        default=False,
        verbose_name='Repository is Live?'
    )
    limit_upload_to_pdf = models.BooleanField(
        default=False,
        help_text=_('If set to True, this will require all file uploads from'
                    'authors to be PDF files.')
    )
    about = models.TextField(blank=True, null=True)
    start = models.TextField(
        blank=True,
        null=True,
        verbose_name='Submission Start Text',
    )
    submission = models.TextField(blank=True, null=True)
    publication = models.TextField(blank=True, null=True)
    decline = models.TextField(blank=True, null=True)
    accept_version = models.TextField(blank=True, null=True)
    decline_version = models.TextField(blank=True, null=True)
    new_comment = models.TextField(blank=True, null=True)
    footer = models.TextField(
        blank=True,
        null=True,
        default='<p>Powered by Janeway</p>',
    )
    login_text = models.TextField(
        blank=True,
        null=True,
        help_text='If text is added it will display on the login '
                  'and register pages.',
        verbose_name='Account Page Text'
    )
    submission_agreement = models.TextField(
        null=True,
        help_text="Add any information that the author may need to know as "
                  "part of their submission, eg. Copyright transfer etc.'",
        default="<p>Authors grant us the right to publish, on this website, "
                "their uploaded manuscript, supplementary materials and "
                "any supplied metadata.</p>",
    )

    random_homepage_preprints = models.BooleanField(default=False)
    homepage_preprints = models.ManyToManyField(
        'submission.Article',
        blank=True,
    )

    class Meta:
        verbose_name_plural = 'repositories'

    @classmethod
    def get_by_request(cls, request):
        domain = request.get_host()
        # Lookup by domain with/without port
        try:
            obj = cls.objects.get(
                domain=domain,
                live=True,
            )
        except cls.DoesNotExist:
            # Lookup without port
            domain, _port = split_domain_port(domain)
            obj = cls.objects.get(
                domain=domain,
                live=True
            )
        return obj

    def __str__(self):
        return '[{}] {}'.format(
            'live' if self.live else 'disabled',
            self.name,
        )

    def top_level_subjects(self):
        return Subject.objects.filter(
            repository=self,
            parent=None,
        ).prefetch_related(
            'children'
        )

    def additional_submission_fields(self):
        return RepositoryField.objects.filter(
            repository=self,
        )

    def site_url(self, path=""):
        if settings.URL_CONFIG == "path":
            return self._site_path_url(path)

        return logic.build_url(
                netloc=self.domain,
                scheme=self.SCHEMES[self.is_secure],
                port=None,
                path=path,
        )

    def _site_path_url(self, path=None):
        request = logic.get_current_request()
        if request and request.repository == self:
            if not path:
                path = "/{}".format(self.short_name)
            return request.build_absolute_uri(path)
        else:
            return request.press.repository_path_url(self, path)


class RepositoryField(models.Model):
    repository = models.ForeignKey(Repository)
    name = models.CharField(max_length=255)
    input_type = models.CharField(
        max_length=255,
        choices=html_input_types(),
    )
    choices = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text='Separate choices with the bar | character.',
    )
    required = models.BooleanField(default=True)
    order = models.IntegerField()
    help_text = models.TextField(blank=True, null=True)
    display = models.BooleanField(
        default=False,
        help_text='Whether or not display this field in the article page',
    )
    dc_metadata_type = models.CharField(
        max_length=255,
        help_text=_(
            'If this field is to be output as a dc metadata field you can add'
            'the type here.'
        ),
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ('order', 'name',)

    def __str__(self):
        return '{}: {}'.format(self.repository.name, self.name)


class RepositoryFieldAnswer(models.Model):
    field = models.ForeignKey(
        RepositoryField,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    preprint = models.ForeignKey('Preprint')
    answer = models.TextField()

    def __str__(self):
        return '{}: {}'.format(self.preprint, self.answer)


class Preprint(models.Model):
    repository = models.ForeignKey(
        Repository,
        null=True,
        on_delete=models.SET_NULL,
    )
    owner = models.ForeignKey(
        'core.Account',
        null=True,
        on_delete=models.SET_NULL,
        help_text='The account that submitted this item.',
    )
    stage = models.CharField(max_length=25, default=STAGE_PREPRINT_UNSUBMITTED)
    title = models.CharField(
        max_length=300,
        help_text=_('Your article title'),
    )
    abstract = models.TextField(
        blank=True,
        null=True,
        help_text=_(
            'Please avoid pasting content from word processors as they can add '
            'unwanted styling to the abstract. You can retype the abstract '
            'here or copy and paste it into notepad/a plain text editor before '
            'pasting here.',
        )

    )
    submission_file = models.ForeignKey(
        'PreprintFile',
        related_name='submission_file',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    meta_image = models.ImageField(
        blank=True,
        null=True,
        upload_to=preprint_file_upload,
        storage=preprint_media_store,
    )
    subject = models.ManyToManyField(
        'Subject',
        blank=False,
        null=True,
    )
    keywords = models.ManyToManyField(
        'submission.Keyword',
        blank=True,
        null=True,
    )
    license = models.ForeignKey(
        'submission.Licence',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    comments_editor = models.TextField(
        blank=True,
        null=True,
        verbose_name="Comments to the Editor",
        help_text="Add any comments you'd like the editor to consider here.",
    )
    doi = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='Published DOI',
        help_text='You can add a DOI linking to this item\'s published version using this field. '
                  'Please provide the full DOI ie. https://doi.org/10.1017/CBO9781316161012.'
    )
    preprint_doi = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='Preprint DOI',
        help_text='System supplied DOI. '
    )
    preprint_decision_notification = models.BooleanField(
        default=False,
    )
    date_started = models.DateTimeField(default=timezone.now)
    date_submitted = models.DateTimeField(blank=True, null=True)
    date_accepted = models.DateTimeField(blank=True, null=True)
    date_declined = models.DateTimeField(blank=True, null=True)
    date_published = models.DateTimeField(blank=True, null=True)
    date_updated = models.DateTimeField(blank=True, null=True)
    current_step = models.IntegerField(default=1)

    def __str__(self):
        return '{}'.format(
            self.title,
        )

    def old_versions(self):
        return PreprintVersion.objects.filter(
            preprint=self,
        ).exclude(
            preprint=self.current_version,
        )

    @property
    def current_version(self):
        try:
            return self.preprintversion_set.all()[0]
        except IndexError:
            return None

    def version_files(self):
        return [
            version.file for version in self.preprintversion_set.filter(
                Q(moderated_version__approved=True) | Q(moderated_version__isnull=True)
            )
        ]

    @property
    @cache(300)
    def views(self):
        return PreprintAccess.objects.filter(
            preprint=self,
            file__isnull=True
        )

    @property
    @cache(300)
    def downloads(self):
        return PreprintAccess.objects.filter(
            preprint=self,
            file__isnull=False,
        )

    def next_author_order(self):
        try:
            last_author = self.preprintauthor_set.all().reverse()[0]
            return last_author.order + 1
        except IndexError:
            return 0

    def next_version_number(self):
        try:
            last_version = self.preprintversion_set.all()[0]
            return last_version.version + 1
        except IndexError:
            return 1

    @property
    def authors(self):
        preprint_authors = PreprintAuthor.objects.filter(
            preprint=self,
        ).select_related('author')

        return [pa.author for pa in preprint_authors]

    @property
    def supplementaryfiles(self):
        return PreprintSupplementaryFile.objects.filter(
            preprint=self,
        )

    def author_objects(self):
        pks = [author.pk for author in self.authors]
        return Author.objects.filter(pk__in=pks)

    def display_authors(self):
        return ", ".join([author.full_name for author in self.authors])

    def add_user_as_author(self, user):
        author_dict = {
            'first_name': user.first_name if user.first_name else '',
            'middle_name': user.middle_name if user.middle_name else '',
            'last_name': user.last_name if user.last_name else '',
            'affiliation': user.affiliation() if user.affiliation else '',
        }
        author, a_created = Author.objects.get_or_create(
            email_address=user.email,
            defaults=author_dict,
        )
        preprint_author, created = PreprintAuthor.objects.get_or_create(
            author=author,
            preprint=self,
            defaults={'order': self.next_author_order()},
        )

        return created

    def add_author(self, author):
        preprint_author, created = PreprintAuthor.objects.get_or_create(
            author=author,
            preprint=self,
            order=self.next_author_order(),
        )

        return preprint_author, created

    def add_supplementary_file(self, supplementary):
        return PreprintSupplementaryFile.objects.get_or_create(
            label=supplementary.cleaned_data['label'],
            url=supplementary.cleaned_data['url'],
            preprint=self,
            defaults={
                'order': self.next_supp_file_order()
            },
        )

    def next_supp_file_order(self):
        orderings = [supp_file.order for supp_file in self.supplementaryfiles]
        return max(orderings) + 1 if orderings else 0


    def user_is_author(self, user):
        if user.email in [author.email_address for author in self.authors]:
            return True

        return False

    def set_file(self, file, original_filename):
        self.submission_file.original_filename = original_filename
        self.submission_file.file = file
        self.submission_file.save()

    def submit_preprint(self):
        self.date_submitted = timezone.now()
        self.stage = STAGE_PREPRINT_REVIEW
        self.current_step = 5
        self.save()

    def subject_editors(self):
        editors = []
        for subject in self.subject.all():
            for editor in subject.editors.all():
                editors.append(editor)

        return editors

    def has_version(self):
        return self.preprintversion_set.all()

    def additional_field_answers(self):
        return self.repositoryfieldanswer_set.all()

    def display_additional_fields(self):
        return self.repositoryfieldanswer_set.filter(
            field__display=True,
        )

    def make_new_version(self, file):
        PreprintVersion.objects.create(
            preprint=self,
            file=file,
            version=self.next_version_number(),
        )

    def update_date_published(self, date, time):
        self.date_published = dateparser.parse(
            '{date} {time}'.format(
                date=date,
                time=time,
            )
        )
        self.save()

    def accept(self, date, time):
        self.date_accepted = timezone.now()
        self.date_declined = None
        self.stage = STAGE_PREPRINT_PUBLISHED
        self.date_published = dateparser.parse(
            '{date} {time}'.format(
                date=date,
                time=time,
            )
        )
        self.save()

    def decline(self):
        self.date_declined = timezone.now()
        self.date_accepted = None
        self.stage = STAGE_PREPRINT_REJECTED
        self.save()

    def reset(self):
        self.date_accepted = None
        self.date_declined = None
        self.date_published = None
        self.preprint_decision_notification = False
        self.stage = STAGE_PREPRINT_REVIEW
        self.save()

    def is_published(self):
        if self.stage == STAGE_PREPRINT_PUBLISHED and self.date_published:
            return True
        return False

    def current_version_file_type(self):
        print(self.current_version)
        if self.current_version.file.mime_type in files.HTML_MIMETYPES:
            return 'html'
        elif self.current_version.file.mime_type in files.PDF_MIMETYPES:
            return 'pdf'
        return None

    @property
    @cache(600)
    def url(self):
        return self.repository.site_url(path=self.local_url)

    @property
    def local_url(self):
        url = reverse(
            'repository_preprint',
            kwargs={'preprint_id': self.id,}
        )

        return url




class PreprintFile(models.Model):
    preprint = models.ForeignKey(Preprint)
    file = models.FileField(
        upload_to=preprint_file_upload,
        storage=preprint_file_store,
    )
    original_filename = models.TextField()
    uploaded = models.DateTimeField(default=timezone.now)
    mime_type = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )
    size = models.PositiveIntegerField(default=0)

    def filename(self):
        return os.path.basename(self.file.name)

    @property
    def uuid_filename(self):
        return self.filename()

    def get_file_mime_type(self):
        return files.file_path_mime(self.file.path)

    def path_parts(self):
        path = os.path.dirname(os.path.abspath(self.file.path))
        return path

    def reverse_kwargs(self):
        return {
            'preprint_id': self.preprint.pk,
            'file_id': self.pk,
        }

    def download_url(self):
        return reverse(
            'repository_download_file',
            kwargs=self.reverse_kwargs(),
        )

    def contents(self):
        file = open(self.file.path, mode='r')
        contents = file.read()
        file.close()
        return contents


class PreprintSupplementaryFile(models.Model):
    preprint = models.ForeignKey(Preprint)
    url = models.URLField()
    label = models.CharField(max_length=200, verbose_name=_('Label'), default='Supplementary File')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('order',)
        unique_together = ('url', 'preprint')


class PreprintAccess(models.Model):
    preprint = models.ForeignKey(Preprint)
    file = models.ForeignKey(PreprintFile, blank=True, null=True)
    identifier = models.TextField(blank=True, null=True)
    accessed = models.DateTimeField(auto_now_add=True)
    country = models.ForeignKey('core.Country', blank=True, null=True)

    @property
    def access_type(self):
        if self.file:
            return 'download'
        return 'view'


class PreprintAuthor(models.Model):
    preprint = models.ForeignKey('Preprint')
    author = models.ForeignKey('Author')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('order',)
        unique_together = ('author', 'preprint')

    def __str__(self):
        return '{author} linked to {preprint}'.format(
            author=self.author.full_name,
            preprint=self.preprint.title,
        )


class Author(models.Model):
    email_address = models.EmailField(unique=True)
    first_name = models.CharField(max_length=255)
    middle_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255)
    affiliation = models.TextField(blank=True, null=True)
    orcid = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_('ORCID')
    )

    class Meta:
        ordering = ('last_name',)

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        if not self.middle_name:
            return '{} {}'.format(self.first_name, self.last_name)
        else:
            return '{} {} {}'.format(
                self.first_name,
                self.middle_name,
                self.last_name,
            )

    def dc_name(self):
        if not self.middle_name:
            return '{}, {}'.format(self.last_name, self.first_name)
        else:
            return '{}. {} {}'.format(
                self.last_name,
                self.first_name,
                self.middle_name,
            )

    def to_dc(self):
        return '<meta name="DC.Contributor" content="{}">'.format(
            self.dc_name,
        )


class PreprintVersion(models.Model):
    preprint = models.ForeignKey(Preprint)
    file = models.ForeignKey(PreprintFile)
    version = models.IntegerField(default=1)
    date_time = models.DateTimeField(default=timezone.now)
    moderated_version = models.ForeignKey(
        'VersionQueue',
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ('-version', '-date_time', '-id')

    def html(self):
        if self.file.mime_type in files.HTML_MIMETYPES:
            return self.file.contents()
        else:
            return ''


class Comment(models.Model):
    author = models.ForeignKey(
        'core.Account',
        null=True,
        on_delete=models.SET_NULL,
    )
    preprint = models.ForeignKey(
        Preprint,
        null=True,
        on_delete=models.SET_NULL,
    )
    reply_to = models.ForeignKey(
        'self',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    date_time = models.DateTimeField(default=timezone.now)
    body = models.TextField(verbose_name='Write your comment:')
    is_reviewed = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)

    class Meta:
        ordering = ('-date_time', '-pk')

    def __str__(self):
        return 'Comment by {author} on {article}'.format(
            author=self.author.full_name(),
            article=self.preprint.title,
        )
    
    def mark_public(self):
        if self.is_public:
            self.is_public = False
        else:
            self.is_public = True

        self.is_reviewed = True
        self.save()

    def mark_reviewed(self):
        self.is_reviewed = True
        self.save()


class Subject(models.Model):
    repository = models.ForeignKey(Repository)
    name = models.CharField(max_length=255)
    slug = models.SlugField(blank=True, max_length=255)
    editors = models.ManyToManyField('core.Account', blank=True)
    enabled = models.BooleanField(
        default=True,
        help_text='If disabled, this subject will not appear publicly.',
    )
    parent = models.ForeignKey(
        'self',
        blank=True,
        null=True,
        related_name='children',
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ('slug', 'pk')

    def __str__(self):
        return self.name


def version_choices():
    return (
        ('correction', 'Correction'),
        ('version', 'New Version'),
    )


class VersionQueue(models.Model):
    preprint = models.ForeignKey(Preprint)
    file = models.ForeignKey(PreprintFile)
    update_type = models.CharField(max_length=10, choices=version_choices())

    date_submitted = models.DateTimeField(default=timezone.now)
    date_decision = models.DateTimeField(blank=True, null=True)
    approved = models.BooleanField(default=False)

    def approve(self):
        self.date_decision = timezone.now()
        self.approved = True
        self.save()

    def decline(self):
        self.date_decision = timezone.now()
        self.approved = False
        self.save()

    def decision(self):
        if self.date_decision and self.approved:
            return True
        elif self.date_decision:
            return False

    def status(self):
        if self.date_decision and self.approved:
            return _('Approved')
        elif not self.date_decision:
            return _('Under Review')
        else:
            return _('Declined')


@receiver(models.signals.post_delete, sender=PreprintFile)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """
    Deletes file from filesystem
    when corresponding `PreprintFile` object is deleted.
    """
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)


@receiver(models.signals.pre_save, sender=PreprintFile)
def auto_delete_file_on_change(sender, instance, **kwargs):
    """
    Deletes old file from filesystem
    when corresponding `PreprintFile` object is updated
    with new file.
    """
    if not instance.pk:
        return False

    try:
        old_file = PreprintFile.objects.get(pk=instance.pk).file
    except PreprintFile.DoesNotExist:
        return False

    new_file = instance.file
    if not old_file == new_file:
        if os.path.isfile(old_file.path):
            os.remove(old_file.path)


@receiver(models.signals.pre_save, sender=Repository)
def add_email_setting_defaults(sender, instance, **kwargs):
    """
    When a new Repository is added we insert the email settings onto the
    instance before it is saved.
    """
    if instance._state.adding:
        install.load_settings(instance)
