from django.db import models
from django.forms import TextInput
from django.contrib import admin
from solo.admin import SingletonModelAdmin
from adminsortable.admin import SortableAdmin
from .models import Agency, Beat, Bureau, CallSource, CallUnit, City, CloseCode, \
    District, Division, Nature, NatureGroup, \
    Officer, \
    Priority, Shift, ShiftUnit, SiteConfiguration, Squad, \
    Transaction, Unit


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(SingletonModelAdmin):
    model = SiteConfiguration
    fieldsets = (
        (None, {
            'fields': ('maintenance_mode',)
        }),
        ('Features', {
            'fields': (
                'use_shift',
                'use_district',
                'use_beat',
                'use_squad',
                'use_priority',
                'use_nature',
                'use_nature_group',
                'use_call_source',
                'use_cancelled',
            ),
        }),
        ('Geography', {
            'fields': (
                'geo_center',
                'geo_ne_bound',
                'geo_sw_bound',
                'geo_default_zoom',
                'geojson_url',
            )
        })
    )


# model inline classes

class BeatInline(admin.TabularInline):
    model = Beat
    extra = 0
    exclude = ('sector',)
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


class CallUnitInline(admin.TabularInline):
    model = CallUnit
    extra = 0
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


class NatureInline(admin.StackedInline):
    model = Nature
    extra = 0
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }
    can_delete = False


class ShiftUnitInline(admin.TabularInline):
    model = ShiftUnit
    extra = 0


# model admin classes

@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ('descr', 'code',)


@admin.register(Beat)
class BeatAdmin(admin.ModelAdmin):
    list_display = ('descr', 'district',)
    inlines = [CallUnitInline]
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


@admin.register(Bureau)
class BureauAdmin(admin.ModelAdmin):
    list_display = ('descr', 'code',)
    inlines = [ShiftUnitInline]
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


@admin.register(CallSource)
class CallSourceAdmin(admin.ModelAdmin):
    list_display = ('descr', 'code', 'is_self_initiated',)
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


@admin.register(CallUnit)
class CallUnitAdmin(admin.ModelAdmin):
    list_display = ('descr', 'squad', 'beat', 'district', 'is_patrol_unit',)
    inlines = [ShiftUnitInline]
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


@admin.register(CloseCode)
class CloseCodeAdmin(admin.ModelAdmin):
    list_display = ('descr', 'code',)
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    exclude = ('sector',)
    inlines = [BeatInline, CallUnitInline]
    formfield_overrides = {
        models.TextField: {'widget': TextInput(attrs={'size': '50'})}
    }


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ('descr', 'code',)
    inlines = [ShiftUnitInline]
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


@admin.register(Nature)
class NatureAdmin(admin.ModelAdmin):
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }
    list_display = ('descr', 'nature_group', 'is_directed_patrol',)


@admin.register(NatureGroup)
class NatureGroupAdmin(admin.ModelAdmin):
    inlines = [NatureInline]
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }
    # filter_horizontal = ('nature_set',)


@admin.register(Officer)
class OfficerAdmin(admin.ModelAdmin):
    list_display = ('name', 'name_aka',)
    inlines = [ShiftUnitInline]


@admin.register(Priority)
class PriorityAdmin(SortableAdmin):
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    inlines = [ShiftUnitInline]


@admin.register(ShiftUnit)
class ShiftUnitAdmin(admin.ModelAdmin):
    pass


@admin.register(Squad)
class SquadAdmin(admin.ModelAdmin):
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('descr', 'code', 'is_start', 'is_end',)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('descr', 'code',)
    inlines = [ShiftUnitInline]
    formfield_overrides = {
        models.TextField: {'widget': TextInput}
    }
