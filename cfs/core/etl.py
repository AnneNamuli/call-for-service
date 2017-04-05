import datetime as dt
import math
import os
import os.path
import re
from itertools import chain
import pandas as pd
import dateparser
from django.db import connection
from django.db.utils import IntegrityError
from django.core.management import call_command
from django.core.exceptions import FieldDoesNotExist
from core.models import *
from officer_allocation.models import *
import psycopg2
from datetime import datetime


# TODO
# - call_latlong
# - beat shapefiles


def flatmap(f, items):
    return chain.from_iterable(map(f, items))


def safe_strip(str_):
    if isnan(str_):
        return ''
    try:
        return str_.strip()
    except AttributeError:
        return str_


def strip_dataframe(df):
    string_cols = list(df.select_dtypes(include=['object']).columns)

    for col in string_cols:
        df[col] = df[col].apply(lambda x: safe_strip(x))


def safe_map(m, d):
    return m.get(d) if d else None


def safe_int(x):
    return int(x) if x else None


def safe_datetime(x):
    # to_datetime returns a pandas Timestamp object, and we want a datetime
    try:
        retval = pd.to_datetime(x).to_pydatetime() if x not in (
            'NULL', 'NaT', None) else None
        if isinstance(retval, pd.tslib.NaTType):
            return None
        else:
            return retval
        # return dateparser.parse(x) if x not in ('NULL', None) else None
    except ValueError:
        return None


def safe_float(x):
    return float(x) if x else None


def safe_bool(x):
    return bool(x)


def clean_case_id(c):
    if c:
        c = str(c).replace('-', '').replace(' ', '')
        try:
            return int(c)
        except ValueError:  # got some weird rows with non-digits in the case_id that def. won't map back to incident
            return None
    return None


def clean_officer_name(name):
    return ', '.join([t.strip() for t in name.split(',')]) if name else ''


timestamp_expr = re.compile(
    "(.*?)\[(\d{2}/\d{2}/(?:\d{2}|\d{4}) \d{2}:\d{2}:\d{2}) (.*?)\]")


def isnan(x):
    return type(x) == float and math.isnan(x)


def unique_clean_values(column):
    return {x.strip()
            for x in pd.unique(column.values)
            if x and not isnan(x) and x.strip()}


def model_has_field(model, field):
    try:
        model._meta.get_field(field)
        return True
    except FieldDoesNotExist:
        return False


class ETL:

    def __init__(self, dir, reset=False, subsample=None, batch_size=2000):
        self.dir = dir
        self.subsample = subsample
        self.mapping = {}
        self.start_time = None
        self.batch_size = batch_size
        self.reset = reset
        self.agency = Agency.objects.first()

    def run(self):
        self.start_time = dt.datetime.now()

        if self.reset:
            self.clear_database()

        self.calls = self.load_calls()

        self.mapping['City'] = self.create_from_calls(column="citydesc",
                                                      model=City,
                                                      to_field="city_id")
        self.mapping['District'] = self.create_from_calls(column="district",
                                                          model=District,
                                                          to_field="district_id")
        self.mapping['Beat'] = self.create_from_calls(column="statbeat",
                                                      model=Beat,
                                                      to_field="beat_id")
        self.mapping['Nature'] = self.create_from_calls(column="nature",
                                                        model=Nature,
                                                        to_field="nature_id")
        self.mapping['Priority'] = self.create_from_calls(column="priority",
                                                          model=Priority,
                                                          to_field="priority_id")
        self.mapping['CallSource'] = self.create_from_lookup(
            model=CallSource,
            filename="inmain.callsource.tsv",
            mapping={"descr": "Description"},
            code_column="code_agcy",
            to_field="call_source_id")
        self.mapping['CallUnit'] = self.create_call_units_from_calls()
        self.mapping['CloseCode'] = self.create_from_lookup(
            filename="inmain.closecode.tsv",
            model=CloseCode,
            mapping={"descr": "Description"},
            code_column="code_agcy",
            to_field="close_code_id")
        self.mapping['Bureau'] = self.create_from_lookup(
            filename="LWMAIN.EMUNIT.csv",
            model=Bureau,
            mapping={"descr": "descriptn"},
            code_column="code_agcy",
            to_field="bureau_id")
        self.mapping['Unit'] = self.create_from_lookup(
            filename="LWMAIN.EMSECTION.csv",
            model=Unit,
            mapping={"descr": "descriptn"},
            code_column="code_agcy",
            to_field="unit_id")
        self.mapping['Division'] = self.create_from_lookup(
            filename="LWMAIN.EMDIVISION.csv",
            model=Division,
            mapping={"descr": "descriptn"},
            code_column="code_agcy",
            to_field="division_id")
        self.mapping['OOSCode'] = self.create_from_lookup(
            filename="outserv.oscode.tsv",
            model=OOSCode,
            mapping={"descr": "Description"},
            code_column="Code",
            to_field="oos_code_id"
        )
        self.connect_beats_districts()
        self.create_calls()
        self.calls = None

        self.in_service = self.load_in_service()
        self.mapping['CallUnit'] = self.create_call_units_from_in_service()
        self.mapping['Shift'] = self.create_shifts()
        self.mapping['Officer'] = self.create_officers()
        self.create_shift_units()
        self.in_service = None

        self.call_log = self.load_call_log()
        self.shrink_call_log()
        self.mapping['CallUnit'] = self.create_call_units_from_call_log()
        self.mapping['Transaction'] = self.create_transactions()
        self.create_call_log()
        self.call_log = None

        self.create_out_of_service()

        self.connect_call_unit_squads()
        self.connect_call_unit_beat_district()

        self.create_nature_groups()
        self.create_officer_activity_types()

        self.log("Updating materialized views")
        update_materialized_views()

    def clear_database(self):
        self.log("Clearing database")
        call_command("flush", interactive=False)

    def log(self, message):
        if self.start_time:
            current_time = dt.datetime.now()
            period = current_time - self.start_time
        else:
            period = dt.timedelta(0)
        print("[{:7.2f}] {}".format(period.total_seconds(), message))

    def map(self, model_name, value):
        return safe_map(self.mapping[model_name], value)

    def load_calls(self):
        self.log("Loading calls...")

        filename = os.path.join(self.dir, "cfs_2014_inmain.csv")
        df = pd.read_csv(filename, encoding='ISO-8859-1',
                         dtype={"streetno": "object"})
        strip_dataframe(df)

        if self.subsample:
            df = df.sample(frac=self.subsample)

        df = self.exclude_existing(df, Call, 'inci_id', 'call_id')

        return df

    def get_key_set(self, model, key_col):
        return set(model.objects.values_list(key_col, flat=True))

    def exclude_existing(self, df, model, data_key_col, db_key_col):
        existing_ids = self.get_key_set(model, db_key_col)
        return df[df.apply(lambda x: x[data_key_col] not in existing_ids, axis=1)]

    def create_from_calls(self, column, model, to_field, from_field='descr'):
        self.log("Creating {} data from calls...".format(model.__name__))
        xs = unique_clean_values(self.calls[column])
        xs -= self.get_key_set(model, from_field)

        if model_has_field(model, 'agency'):
            model.objects.bulk_create(
                model(**{from_field: x, 'agency': self.agency}) for x in xs)
        else:
            model.objects.bulk_create(model(**{from_field: x}) for x in xs)

        return dict(model.objects.values_list(from_field, to_field))

    def create_from_lookup(self, model, filename, mapping, code_column,
                           to_field, from_field='code'):
        self.log("Creating {} data from {}...".format(
            model.__name__, filename))
        model_data = {}

        if filename.endswith(".csv"):
            data = pd.read_csv(os.path.join(self.dir, filename))
        elif filename.endswith(".tsv"):
            data = pd.read_csv(os.path.join(self.dir, filename), sep='\t')

        data = self.exclude_existing(data, model, code_column, from_field)

        for idx, row in data.iterrows():
            md = {}
            for k, v in mapping.items():
                md[k] = row[v]
            model_data[row[code_column]] = md

        model.objects.bulk_create(
            model(code=k, **v) for k, v in model_data.items())
        return dict(model.objects.values_list(from_field, to_field))

    def create_call_units_from_calls(self):
        self.log("Creating call units from calls...")
        return self.create_call_units_from_values(
            list(self.calls.primeunit.values) +
            list(self.calls.firstdisp.values) +
            list(self.calls.reptaken.values))

    def create_call_units_from_in_service(self):
        self.log("Creating call units from in service...")
        return self.create_call_units_from_values(
            list(self.in_service.unitcode.values))

    def create_call_units_from_call_log(self):
        self.log("Creating call units from call log...")
        return self.create_call_units_from_values(
            list(self.call_log.unitcode.values))

    def create_call_units_from_values(self, values):
        current_unit_descrs = self.get_key_set(CallUnit, 'descr')
        unitset = {unit.strip() for unit in values if
                   unit and not isnan(unit) and unit.strip()}
        units_to_create = unitset - current_unit_descrs
        CallUnit.objects.bulk_create(CallUnit(agency=self.agency, descr=unit)
                                     for unit in units_to_create)
        return dict(CallUnit.objects.values_list('descr', 'call_unit_id'))

    def create_calls(self):
        from django.forms.models import model_to_dict
        try:
            start = 0
            while start < len(self.calls):
                batch = self.calls[start:start + self.batch_size]
                calls = []

                for idx, c in batch.iterrows():
                    call = Call(call_id=c.inci_id,
                                agency=self.agency,
                                time_received=safe_datetime(c.calltime),
                                case_id=clean_case_id(c.case_id),
                                call_source_id=self.map('CallSource',
                                                        c.callsource),
                                primary_unit_id=self.map('CallUnit',
                                                         c.primeunit),
                                first_dispatched_id=self.map('CallUnit',
                                                             c.firstdisp),
                                street_address="{} {}".format(
                                    c.streetno, c.streetonly),
                                city_id=self.map('City', c.citydesc),
                                zip_code=c.zip,
                                crossroad1=c.crossroad1,
                                crossroad2=c.crossroad2,
                                geox=safe_float(c.geox),
                                geoy=safe_float(c.geoy),
                                beat_id=self.map('Beat', c.statbeat),
                                district_id=self.map('District', c.district),
                                business=c.business,
                                nature_id=self.map('Nature', c.nature),
                                priority_id=self.map('Priority', c.priority),
                                report_only=safe_bool(c.rptonly),
                                cancelled=safe_bool(c.cancelled),
                                time_routed=safe_datetime(c.timeroute),
                                time_finished=safe_datetime(c.timefini),
                                first_unit_dispatch=safe_datetime(c.firstdtm),
                                first_unit_enroute=safe_datetime(c.firstenr),
                                first_unit_arrive=safe_datetime(c.firstarrv),
                                last_unit_clear=safe_datetime(c.lastclr),
                                time_closed=safe_datetime(c.timeclose),
                                reporting_unit_id=self.map('CallUnit',
                                                           c.reptaken),
                                close_code_id=self.map('CloseCode',
                                                       c.closecode),
                                close_comments=c.closecomm)
                    call.update_derived_fields()
                    calls.append(call)
                Call.objects.bulk_create(calls)
                self.log("Call {}-{} created".format(start, start + len(batch)))
                start += self.batch_size
        except ValueError as ex:
            import pdb
            pdb.set_trace()

    def connect_beats_districts(self):
        self.log("Connecting beats to districts...")

        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE beat
                SET district_id = (
                  SELECT district_id
                  FROM district
                  WHERE district.descr = 'D' || SUBSTRING(beat.descr::text FROM 1 FOR 1)
                )
                WHERE beat.descr NOT IN ('DSO', 'OOJ');
            """)

    def connect_call_unit_squads(self):
        self.log("Connecting call units and squads...")
        call_unit_squad_regexes = {
            'A': '^A[1-5][0-9]{2}$',
            'B': '^B[1-5][0-9]{2}$',
            'C': '^C[1-5][0-9]{2}$',
            'D': '^D[1-5][0-9]{2}$',
            'BIKE': '^L5[0-9]{2}$',
            'HEAT': '^H[1-4][0-9]{2}$',
            'K9': '^K[0-9]{2}$',
            'MOTORS': '^MTR[2-8]$',
            'TACT': '^T[2-8]$',
            'VIR': '^ED6[0-6]$'
        }

        existing_squads = self.get_key_set(Squad, 'descr')

        Squad.objects.bulk_create(
            Squad(descr=s) for s in call_unit_squad_regexes.keys()
            if s not in existing_squads)
        self.mapping['Squad'] = dict(
            Squad.objects.values_list('descr', 'squad_id'))

        for squad, regex in call_unit_squad_regexes.items():
            CallUnit.objects.filter(descr__regex=regex).update(
                squad_id=self.map('Squad', squad))

    def connect_call_unit_beat_district(self):
        self.log("Connecting call units with beats and districts...")
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE call_unit cu
                SET beat_id = (
                        SELECT beat_id
                        FROM beat b
                        WHERE b.descr = substring(cu.descr FROM 2 FOR 3)
                    ),
                    district_id = (
                        SELECT district_id
                        FROM district d
                        WHERE d.descr = 'D' || substring(cu.descr FROM 2 FOR 1)
                    )
                WHERE cu.descr ~ '[A-D][1-5][0-9][0-9]'
                  AND NOT cu.descr ~ '[A-D][1-5]00';
        """)

    def load_in_service(self):
        self.log("Loading in service data...")
        filename = os.path.join(self.dir, "cfs_2014_unitper.csv")
        df = pd.read_csv(filename, encoding='ISO-8859-1',
                         dtype={"name": "object", 'emdept_id': "object"})
        strip_dataframe(df)

        if self.subsample:
            df = df.sample(frac=self.subsample)

        df = self.exclude_existing(df, Shift, 'unitperid', 'shift_id')

        return df

    def create_shifts(self):
        self.log("Create shifts from in service data...")
        shift_ids = set(pd.unique(self.in_service.unitperid.values))
        Shift.objects.bulk_create(Shift(shift_id=id) for id in shift_ids)
        return dict(Shift.objects.values_list('shift_id', 'shift_id'))

    def create_officers(self):
        self.log("Creating officers from in service data...")
        officers = {}
        existing_officers = self.get_key_set(Officer, 'officer_id')
        for idx, row in self.in_service.iterrows():
            id = row.officerid
            name = clean_officer_name(row['name'])

            # Only load new officers if we don't already have them in the db
            if id not in officers and id not in existing_officers:
                if name.isdigit():
                    officers[id] = {'name_aka': [name]}
                else:
                    officers[id] = {'name': name, 'name_aka': []}
            # Keep track of all names of new officers
            elif id not in officers:
                if ('name' in officers[id] or name.isdigit()) and \
                    name and name not in officers[id]['name_aka'] and \
                        name != officers[id]['name']:
                    officers[id]['name_aka'].append(name)
                elif not ('name' in officers[id] or name.isdigit()):
                    officers[id]['name'] = name
        Officer.objects.bulk_create(
            Officer(officer_id=k, **v) for k, v in officers.items())
        return dict(Officer.objects.values_list('name', 'officer_id'))

    def create_shift_units(self):
        try:
            start = 0
            while start < len(self.in_service):
                batch = self.in_service[start:start + self.batch_size]
                shift_units = []

                for idx, s in batch.iterrows():
                    shift_unit = ShiftUnit(shift_unit_id=s.primekey,
                                           shift_id=self.map('Shift',
                                                             s.unitperid),
                                           call_unit_id=self.map('CallUnit',
                                                                 s.unitcode),
                                           officer_id=safe_int(s.officerid),
                                           in_time=safe_datetime(s.intime),
                                           out_time=safe_datetime(s.outtime),
                                           bureau_id=self.map('Bureau',
                                                              s.emunit),
                                           division_id=self.map('Division',
                                                                s.emdivision),
                                           unit_id=self.map('Unit',
                                                            s.emsection))

                    shift_units.append(shift_unit)

                ShiftUnit.objects.bulk_create(shift_units)
                self.log(
                    "ShiftUnit {}-{} created".format(start, start + len(batch)))
                start += self.batch_size
        except ValueError as ex:
            import pdb
            pdb.set_trace()

    def create_out_of_service(self):
        filename = os.path.join(self.dir, "cfs_2014_outserv.csv")
        df = pd.read_csv(filename, encoding='ISO-8859-1')
        strip_dataframe(df)

        df = self.exclude_existing(df, OutOfServicePeriod, 'outservid',
                                   'oos_id')

        start = 0
        while start < len(df):
            batch = df[start:start + self.batch_size]
            ooss = []

            for idx, s in batch.iterrows():
                oos = OutOfServicePeriod(oos_id=safe_int(s.outservid),
                                         call_unit_id=self.map('CallUnit',
                                                               s.unitcode),
                                         oos_code_id=self.map('OOSCode',
                                                              s.oscode),
                                         location=s.location,
                                         comments=s.comments,
                                         start_time=safe_datetime(s.starttm),
                                         end_time=safe_datetime(s.endtm),
                                         shift_id=self.map('Shift',
                                                           s.unitperid))
                oos.update_derived_fields()
                ooss.append(oos)

            OutOfServicePeriod.objects.bulk_create(ooss)
            self.log("OutOfServicePeriod {}-{} created".format(start,
                                                               start + len(
                                                                   batch)))
            start += self.batch_size

    def load_call_log(self):
        self.log("Loading call log...")
        months = (
            "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
            "oct", "nov", "dec")
        dfs = []
        for month in months:
            filename = os.path.join(self.dir,
                                    "cfs_{}2014_incilog.csv".format(month))
            if not os.path.isfile(filename):
                continue

            df = pd.read_csv(filename, encoding='ISO-8859-1')
            df = self.exclude_existing(df, CallLog, 'incilogid', 'call_log_id')
            dfs.append(df)

        df = pd.concat(dfs)
        strip_dataframe(df)

        df['transtype'] = df['transtype'].map(lambda x: x.upper())
        return df

    def shrink_call_log(self):
        self.log("Removing fire and EMS calls from call log...")
        call_ids = set(Call.objects.all().values_list('call_id', flat=True))
        criterion = self.call_log['inci_id'].map(
            lambda id: str(id) in call_ids)
        df = self.call_log.loc[criterion]
        self.call_log = df

    def create_transactions(self):
        self.log("Creating transactions from call log...")
        transactions = {}

        trans_data = self.call_log[["transtype", "descript"]]
        grouped = trans_data.groupby("transtype")
        for code, row in grouped.first().iterrows():
            transactions[code] = row.descript

        existing_codes = self.get_key_set(Transaction, 'code')
        transactions = {code: descr for code, descr in transactions.items()
                        if code not in existing_codes}

        Transaction.objects.bulk_create(
            Transaction(code=code, descr=descr) for code, descr in
            transactions.items())
        return dict(Transaction.objects.values_list('code', 'transaction_id'))

    def create_call_log(self):
        self.log("Creating call log...")
        existing_ids = self.get_key_set(CallLog, 'call_log_id')

        try:
            start = 0
            while start < len(self.call_log):
                batch = self.call_log[start:start + self.batch_size]
                cls = []

                for idx, s in batch.iterrows():
                    call_log_id = safe_int(s.incilogid)

                    if call_log_id not in existing_ids:
                        cl = CallLog(call_log_id=safe_int(s.incilogid),
                                     transaction_id=self.map('Transaction',
                                                             s.transtype),
                                     time_recorded=safe_datetime(s.timestamp),
                                     call_id=safe_int(s.inci_id),
                                     call_unit_id=self.map(
                                         'CallUnit', s.unitcode),
                                     shift_id=self.map('Shift', s.unitperid),
                                     close_code_id=self.map('CloseCode',
                                                            s.closecode))
                        cls.append(cl)

                CallLog.objects.bulk_create(cls)
                self.log(
                    "CallLog {}-{} created".format(start, start + len(batch)))
                start += self.batch_size
        except ValueError as ex:
            import pdb
            pdb.set_trace()

    def create_nature_groups(self):
        self.log("Creating nature groups...")
        filename = os.path.join(self.dir, "nature_grouping.csv")
        df = pd.read_csv(filename, encoding='ISO-8859-1')

        strip_dataframe(df)

        groups = unique_clean_values(df['group'])

        existing_groups = self.get_key_set(NatureGroup, 'descr')
        groups = [g for g in groups if g not in existing_groups]

        NatureGroup.objects.bulk_create(NatureGroup(descr=g) for g in groups)
        self.mapping['NatureGroup'] = dict(
            NatureGroup.objects.values_list('descr', 'nature_group_id'))

        for idx, row in df.iterrows():
            Nature.objects.filter(descr=row['nature']).update(
                nature_group_id=self.map('NatureGroup', row['group']))

    def create_officer_activity_types(self):
        self.log("Creating officer activity types...")
        types = [
            'IN CALL - CITIZEN INITIATED',
            'IN CALL - SELF INITIATED',
            'IN CALL - DIRECTED PATROL',
            'OUT OF SERVICE',
            'ON DUTY'
        ]

        existing_types = self.get_key_set(OfficerActivityType, 'descr')
        types = [t for t in types if t not in existing_types]

        OfficerActivityType.objects.bulk_create(
            OfficerActivityType(descr=t) for t in types)
