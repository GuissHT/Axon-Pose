from django import forms
from django.contrib.auth.models import User
import re
import unicodedata
from .models import Profile, Question, DoctorAdvice


def _suggest_username(first_name, last_name, current_user=None):
    """Genera un usuario legible y único a partir del nombre completo."""
    normalized_name = unicodedata.normalize('NFKD', f'{first_name} {last_name}')
    normalized_name = normalized_name.encode('ascii', 'ignore').decode('ascii')
    name_parts = re.findall(r'[a-z0-9]+', normalized_name.lower())
    if not name_parts:
        return ''

    base = name_parts[0]
    if len(name_parts) > 1:
        base += name_parts[1][0]

    candidate = base[:150]
    suffix = 2
    while User.objects.filter(username__iexact=candidate).exclude(
        pk=getattr(current_user, 'pk', None)
    ).exists():
        suffix_text = str(suffix)
        candidate = f'{base[:150 - len(suffix_text)]}{suffix_text}'
        suffix += 1
    return candidate


# =============================================================================
# FORMULARIO: UserRegisterForm (Registro de Pacientes)
# Este es el formulario más complejo, ya que une la cuenta de usuario con
# los datos clínicos y el contacto de emergencia.
# =============================================================================
class UserRegisterForm(forms.ModelForm):
    """
    Formulario completo para que el doctor registre a un paciente nuevo.
    """
    # Campos de seguridad (Contraseñas)
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Mínimo 8 caracteres'}),
        label='Contraseña de Acceso',
        min_length=8,
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Repita la contraseña'}),
        label='Confirmar Contraseña',
    )
    
    # Campo oculto para asegurar que el rol sea siempre 'paciente'
    role = forms.CharField(widget=forms.HiddenInput(), initial='patient', required=False)

    # Datos de identificación
    ci = forms.CharField(
        max_length=20,
        required=True,
        label='Cédula de Identidad (CI)',
        widget=forms.TextInput(attrs={'placeholder': 'Ej: 1234567 LP'}),
    )

    # Datos físicos y de contacto
    age = forms.IntegerField(
        label='Edad',
        min_value=1,
        max_value=120,
        widget=forms.NumberInput(attrs={'placeholder': '...'}),
    )
    phone = forms.CharField(
        max_length=8,
        required=True,
        label='Número de Celular (Bolivia)',
        widget=forms.TextInput(attrs={'placeholder': '71234567', 'maxlength': '8'}),
    )

    # Antecedentes clínicos (Área de texto)
    patient_data = forms.CharField(
        label='Antecedentes Clínicos y Alergias',
        required=True,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Ej: Hipertensión, diabetes, alergia a la penicilina...'
        }),
        help_text='Información médica relevante para el seguimiento.',
    )

    # --- Contacto de Referencia (Familiar) ---
    emergency_contact_name = forms.CharField(
        max_length=150,
        required=False,
        label='Nombre del Familiar Responsable',
        widget=forms.TextInput(attrs={'placeholder': 'Ej: Juan Pérez'}),
    )
    emergency_contact_relationship = forms.ChoiceField(
        choices=Profile.RELATIONSHIP_CHOICES,
        required=False,
        label='Parentesco con el Paciente',
    )
    emergency_contact_phone = forms.CharField(
        max_length=8,
        required=False,
        label='Celular del Familiar',
        widget=forms.TextInput(attrs={'placeholder': '71234567', 'maxlength': '8'}),
    )
    emergency_contact_address = forms.CharField(
        max_length=255,
        required=False,
        label='Dirección del Familiar',
        widget=forms.TextInput(attrs={'placeholder': 'Dirección exacta...'}),
    )
    emergency_contact_email = forms.EmailField(
        required=False,
        label='Correo del Familiar (Opcional)',
        widget=forms.EmailInput(attrs={'placeholder': 'familiar@correo.com'}),
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'password']

    def __init__(self, *args, **kwargs):
        """Configuración visual de los campos de texto."""
        super().__init__(*args, **kwargs)
        self.fields['first_name'].label = 'Nombres del Paciente'
        self.fields['last_name'].label = 'Apellidos del Paciente'
        self.fields['email'].label = 'Correo Electrónico'
        self.fields['username'].label = 'Nombre de Usuario'
        self.fields['username'].required = False
        self.fields['username'].help_text = (
            'Se sugiere automáticamente con su nombre; puede modificarlo si lo necesita.'
        )

    # --- Validaciones Especiales ---

    def clean_email(self):
        """Asegura que el correo sea único y esté en minúsculas."""
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            raise forms.ValidationError('El correo es obligatorio.')
        if User.objects.filter(email__iexact=email).exists() and not self.instance.pk:
            raise forms.ValidationError('Ya existe una cuenta con este correo.')
        return email

    def _validate_bolivian_phone(self, value, field_label):
        """Función interna para validar que los celulares tengan 8 dígitos (Bolivia)."""
        # Si el valor está vacío, retornar vacío (es opcional)
        if not value:
            return ''
        digits_only = ''.join(ch for ch in value if ch.isdigit())
        if len(digits_only) != 8:
            raise forms.ValidationError(f'{field_label} debe tener 8 dígitos.')
        return digits_only

    def clean_phone(self):
        return self._validate_bolivian_phone(self.cleaned_data.get('phone'), 'El celular del paciente')

    def clean_emergency_contact_phone(self):
        return self._validate_bolivian_phone(self.cleaned_data.get('emergency_contact_phone'), 'El celular del familiar')

    def clean(self):
        """Verifica que las contraseñas coincidan al registrarse."""
        cleaned_data = super().clean()
        suggested_username = _suggest_username(
            cleaned_data.get('first_name', ''),
            cleaned_data.get('last_name', ''),
            self.instance,
        )
        if not cleaned_data.get('username') or cleaned_data.get('username') == suggested_username:
            cleaned_data['username'] = suggested_username
            if not cleaned_data['username']:
                self.add_error('username', 'Ingrese un nombre y apellido para generar el usuario.')
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError("Las contraseñas no coinciden.")
        return cleaned_data


# =============================================================================
# FORMULARIO: DoctorRegisterForm (Registro de Doctores)
# Solo usado por administradores del sistema.
# =============================================================================
class DoctorRegisterForm(forms.ModelForm):
    """
    Formulario para crear nuevas cuentas de médicos.
    """
    password = forms.CharField(widget=forms.PasswordInput, label='Contraseña')
    password_confirm = forms.CharField(widget=forms.PasswordInput, label='Confirmar Contraseña')
    specialty = forms.CharField(max_length=100, required=True, label='Especialidad Médica')
    phone = forms.CharField(max_length=20, required=True, label='Teléfono de Contacto')

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'password']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].required = False
        self.fields['username'].help_text = (
            'Se sugiere automáticamente con el nombre y apellido del doctor.'
        )

    def clean(self):
        cleaned_data = super().clean()
        suggested_username = _suggest_username(
            cleaned_data.get('first_name', ''),
            cleaned_data.get('last_name', ''),
            self.instance,
        )
        if not cleaned_data.get('username') or cleaned_data.get('username') == suggested_username:
            cleaned_data['username'] = suggested_username
            if not cleaned_data['username']:
                self.add_error('username', 'Ingrese un nombre y apellido para generar el usuario.')
        if cleaned_data.get("password") != cleaned_data.get("password_confirm"):
            raise forms.ValidationError("Las contraseñas no coinciden.")
        return cleaned_data


# =============================================================================
# FORMULARIO: QuestionForm (Preguntas Dinámicas)
# Permite al doctor gestionar el banco de preguntas.
# =============================================================================
class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ['text', 'is_active']
        labels = {
            'text': 'Escriba la pregunta de salud',
            'is_active': '¿Activar ahora para los pacientes?'
        }
        widgets = {
            'text': forms.TextInput(attrs={'placeholder': 'Ej: ¿Se cansa fácilmente al caminar?'})
        }


# =============================================================================
# FORMULARIO: DoctorAdviceForm (Publicación de Consejos)
# Permite al doctor publicar mensajes en el inicio del paciente.
# =============================================================================
class DoctorAdviceForm(forms.ModelForm):
    class Meta:
        model = DoctorAdvice
        fields = ['title', 'message', 'is_active']
        labels = {
            'title': 'Título del consejo (Ej: Recomendación Semanal)',
            'message': 'Mensaje o recomendación detallada',
            'is_active': 'Publicar inmediatamente',
        }
        widgets = {
            'message': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Escriba su recomendación aquí...'}),
        }
