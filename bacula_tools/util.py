from . import *
import bacula_tools
import re, os, sys, filecmp

# {{{ guess_os():

os_bits = {
    'bsd': 'FreeBSD',
    'BSD': 'FreeBSD',
    'Macintosh': 'OSX',
    'OS X': 'OSX',
    'apple-darwin': 'OSX',
    'msie': 'Windows',
    'MSIE': 'Windows',
    }

def guess_os():
    agent = os.environ.get('HTTP_USER_AGENT', '')
    environ = os.environ.get('PATH_INFO','')
    for k in os_bits.keys():
        if k in agent or k in environ:
            return os_bits[k]
    return 'Linux'              # Default

# }}}
# {{{ generate_password():

def generate_password():
    length = 44
    password = []
    possible = 'qwertyuiopasdfghjklzxcvbnmQWERTYUIOPASDFGHJKLZXCVBNM1234567890'
    return ''.join(choice(possible) for _ in xrange(length))

# }}}
# {{{ guess_schedule_and_filesets(hostname, os):


def guess_schedule_and_filesets(hostname, os):
    results = []
    for (variable, matcher, fileset, schedule) in _guessing_rules:
        if matcher.match(locals()[variable]): results.append((fileset, schedule))
    return results or _default_rules

# }}}
    
class ConfigFile(object):       # easy config file management
    FILEHEADER = "# This config file generated by %s script.\n#\n#DO NOT EDIT THIS FILE BY HAND\n\n" % sys.argv[0]
    # {{{ __init__(filename)    # file to update (or not, as the case may be)

    def __init__(self, filename):
        self.filename = filename
        self.newfilename = filename + '.new'
        self.fh = open(self.newfilename, 'w')
        self.fh.write(self.FILEHEADER)
        debug_print("Opened %s", self.newfilename)
        return

    # }}}
    # {{{ close(*data):              # Returns True if an actual update happens

    def close(self, *data):
        if data: self.write(*data)
        self.fh.flush()
        self.fh.close()
        try: test_value = filecmp.cmp(self.filename, self.newfilename)
        except: test_value = False
        if test_value:
            os.unlink(self.newfilename)
            debug_print("\t%s doesn't need to be updated", self.filename)
            return False
        debug_print("\tupdating %s", self.filename)
        os.rename(self.newfilename, self.filename)
        return True

# }}}
    # {{{ write(*data): writes data out to the file, appending newlines for each item passed in

    def write(self, *data):
        for line in data:
            self.fh.write(line)
            self.fh.write('\n')
        return

# }}}
    
class DbDict(dict):             # base class for all of the things derived from database rows
    brace_re = re.compile(r'\s*(.*?)\s*\{\s*(.*)\s*\}\s*', re.MULTILINE|re.DOTALL)
    name_re = re.compile(r'^\s*name\s*=\s*(.*)', re.MULTILINE|re.IGNORECASE)
    SETUP_KEYS = [(NAME, ''), (DATA, '')]
    NULL_KEYS = [ID]
    bc = bacula_tools.Bacula_Factory()
    output = []
    prefix = '  '               # Used for spacing out members when printing
    table = 'override me'       # This needs to be overridden in every subclass, before calling __init__

    # {{{ __init__(row): pass in a row (as a dict)
    def __init__(self, row={}, string = None):
        dict.__init__(self)
        for key, value in self.SETUP_KEYS: self[key] = value
        for key in self.NULL_KEYS: self[key] = None
        self.update(row)
        if string: self.parse_string(string)
        return

    # }}}
    # {{{ search(string, id=None):

    def search(self, string, id=None):
        if string:
            new_me = self.bc.value_check(self.table, NAME, string, asdict=True)
        elif not id == None:
            new_me = self.bc.value_check(self.table, ID, id, asdict=True)
        try: self.update(new_me[0])
        except Exception as e: pass
        return self

    # }}}
    # {{{ delete(): delete it from the database

    def delete(self):
        self.bc.do_sql('DELETE FROM %s WHERE id = %%s' % self.table, self[ID])
        return

# }}}
    # {{{ change_name(name): set my name

    def change_name(self, name):
        self[NAME] = name
        row = self.bc.do_sql('update %s set name = %%s where id = %%s' % self.table, (name, self[ID]))
        return

    # }}}
    # {{{ _set(field, value, bool=False, dereference=False): handy shortcut for setting and saving values

    def _set(self, field, value, bool=False, dereference=False):
        if bool:
            if value in ['0', 'no', 'No', 'NO', 'off', 'Off', 'OFF']: value = 0
            else: value = 1
        if dereference:
            value = self._fk_reference(field, value)[ID]
        self[field] = value
        return self._save()

    # }}}
    # {{{ _save(): Save the top-level fileset record
    def _save(self):
        keys = [x for x in self.keys() if not x == ID]
        keys.sort()
        sql = 'update %s set %s where id = %%s' % (self.table,
                                                   ', '.join(['`%s` = %%s' % x for x in keys]))
        values = [self[x] for x in keys]
        values.append(self[ID])
        return self.bc.do_sql(sql, values)
# }}}
    # {{{ _set_name(name): set my name

    def _set_name(self, name):
        row = self.bc.value_ensure(self.table, NAME, name.strip(), asdict=True)[0]
        self.update(row)
        return

    # }}}
    # {{{ parse_string(string): Entry point for a recursive descent parser

    def parse_string(self, string):
        '''Populate a new object from a string.
        
        We're cheating and treating this object as a blob.
        '''
        g = self.name_re.search(string).groups()
        self._set_name(g[0].strip())
        string = self.name_re.sub('', string)
        data = '\n  '.join([x.strip() for x in string.split('\n') if x])
        self._set(DATA, data)
        return "%s: %s" % (self.table.capitalize(), self[NAME])

    # }}}
    # {{{ _parse_setter(key, c_int=False):

    def _parse_setter(self, key, c_int=False, dereference=False):
        '''Shortcut called by parser for setting values'''
        def rv(value):
            if c_int: self._set(key, int(value[2].strip()), dereference=dereference)
            else: self._set(key, value[2].strip(), dereference=dereference)
        return rv

# }}}
    # {{{ _simple_phrase(key):

    def _simple_phrase(self, key):
        if self[key] == None: return
        try:
            int(self[key])
            value = self[key]
        except: value = '"' + self[key] + '"'
        self.output.insert(-1,'%s%s = %s' % (self.prefix, key.capitalize(), value))
        return

    # }}}
    # {{{ _yesno_phrase(key, onlytrue=False, onlyfalse=False):

    def _yesno_phrase(self, key, onlytrue=False, onlyfalse=False):
        value = self[key]
        if (not value) or value == '0': value = NO
        else: value = YES
        if onlytrue and value == NO: return
        if onlyfalse and value == YES: return
        self.output.insert(-1,'%s%s = %s' % (self.prefix,key.capitalize(), value))
        return

    # }}}
    # {{{ fd(): stub function to make testing a little easier

    def fd(self): return ''

    # }}}
    # {{{ _fk_reference(fk, string=None): Set/get fk-references

    def _fk_reference(self, fk, string=None):
        obj = bacula_tools._DISPATCHER[fk.replace('_id','')]()
        if string:
            obj.search(string.strip())
            if not obj[ID]: obj._set_name(string.strip())
            if not self[fk] == obj[ID]: self._set(fk, obj[ID])
        else: obj.search(None, id=self[fk])
        return obj

# }}}

class PList(list):
    '''This bizarre construct takes a phrase and lazily turns it into a
    list that is all the permutations of the phrase with all spaces
    removed.  Further, this list is sorted such that the first element is
    the original phrase, while the last one has no spaces at all.  It's
    kind of a weird thing, but it makes the string parsing much, much more
    compact and efficient.
    '''
    def __init__(self, phrase):
        list.__init__(self)
        self._expand(phrase)
        return

    def _p2(self, ary):
        if len(ary) == 1: return ary
        if len(ary) == 2: return [''.join(ary), ' '.join(ary)]
        results = []
        for x in self._p2(ary[1:]):
            results.append(ary[0] + x)
            results.append(ary[0] + ' ' + x)
        return results

    def _expand(self, phrase):
        result = self._p2(phrase.split(' '))
        result.sort()
        self.extend(result)
        return
    
class StorageDaemon(DbDict):
    # {{{ __init__(row, timespan, directors):

    def __init__(self, row, timespan, directors):
        DbDict.__init__(self, row)
        self[TIMESPAN] = timespan
        self.directors = directors
        return

    # }}}
    # {{{ print_pool_storage():

    def print_pool_storage(self):
        return '''
Pool {
  Name = %(hostname)s
  Pool Type = Backup
  Recycle = yes
  AutoPrune = yes
  Volume Retention = %(timespan)s
  Maximum Volume Jobs = 1
  Label Format = %(hostname)s-
  Action On Purge = Truncate
}

Storage {
  Name = %(hostname)s
  Address = %(address)s
  SDPort = 9103
  Password = %(password)s
  Device = %(hostname)s
  Media Type = %(hostname)s
  Maximum Concurrent Jobs = 1
}
''' % self

    # }}}
    # {{{ print_device_storage():

    def print_device_storage(self):
        if self[DIRECTOR] == None:
            for d in self.directors:
                if d[PRIMARY_DIR]: self[DIRECTOR_NAME] = d[HOSTNAME]
        else:
            for d in self.directors:
                if d[DIRID] == self[DIRECTOR]: self[DIRECTOR_NAME] = d[HOSTNAME]
        return '''
Storage {
  Name = %(hostname)s
  SDPort = 9103
  WorkingDirectory = "/var/lib/bacula"
  Pid Directory = "/var/run/bacula"
  Maximum Concurrent Jobs = 60
}

Messages {
  Name = Standard
  director = %(director_name)s = all
}
''' % self

# }}}
    # {{{ print_director_access():

    def print_director_access(self):
        result = []
        for d in self.directors:
            result.append('''
Director {
  Name = %s
  Password = %s
}
''' % (d[HOSTNAME], self[PASSWORD]))
        return '\n'.join(result)

    # }}}
                          
class Client(DbDict):           # Should do lots of client stuff all in one place
    # {{{ __init__(row):

    # These two values have to do with formatting the output and are related.
    fmt = '%31s: %s'
    spacer = '\n'+33*' '
    def __init__(self, row):
        DbDict.__init__(self, row)
        bc = Bacula_Factory()
        for x in bc.get_storage_daemons():
            if x[HOSTNAME] == self[STORAGESERVER]:
                self[STORAGESERVERADDRESS] = x[ADDRESS]
                self[STORAGEPASSWORD] = x[PASSWORD]
        self['message_set'] = 'Standard'
        directors = bc.get_directors()
        imadirector = False
        shorthost = os.uname()[1].split('.')[0]
        for d in directors:
            if shorthost in d[HOSTNAME]: imadirector = True
            if not self[DIRECTOR] and d[PRIMARY_DIR]: self[DIRECTOR] = d[DIRID]
            if self[DIRECTOR] == d[DIRID]:
                self[DIRECTOR_NAME] = d[HOSTNAME]
                self[DBNAME] = d[DBNAME]
                self[DBUSER] = d[DBUSER]
                self[DBPASSWORD] = d[DBPASSWORD]
                self[DBADDRESS] = d[DBADDRESS]

        # This is kind of complicated.  If we are running this on an actual
        # director, then we should check to see if the Client's director
        # matches the current host.  If not, mark it disabled (Clients are
        # always disabled on every director but the one to which they
        # belong)
        if self[BACULA_ENABLED] and imadirector:
            my_director = [x for x in directors if shorthost in x[HOSTNAME]]
            if self[DIRECTOR] != my_director[DIRID]: self[BACULA_ENABLED] = 0
        self['bootstrapdir'] = Bacula_Config.BOOTSTRAPDIR
        self[ENABLED] = YES if self[BACULA_ENABLED] else NO
        self[POOL] = self[STORAGESERVER]
        return

    # }}}
    # {{{ __str__(): nice string representation

    def __str__(self):
        result = []
        # This overrides the work in __init__ because it ignores the director information as being irrelevant.
        if self[BACULA_ENABLED] != 0: self[ENABLED] = 'yes'
        else: self[ENABLED] = 'no'
        result.append(self.fmt % (HOSTNAME.capitalize(), '%s (%s)' % (self[HOSTNAME], self[ADDRESS])))
        for key in (HOSTID, ENABLED, FILESET, SCHEDULE, PRIORITY, STORAGESERVER, OS, FILE_RETENTION, JOB_RETENTION, SERVICES, OWNERS, LASTUPDATED):
            result.append(self.fmt % (key.capitalize(), self[key]))

        for key in (BEGIN, END, FAILURE):
            if self[key]: result.append(self.fmt % ('%s Script' % key.capitalize(), self[key]))

        if self[NOTES]: result.append(self.fmt % ('Host Notes', self[NOTES].replace('\n', self.spacer)))
        bacula = Bacula_Factory()
        if self[SERVICES]: service_notes = bacula.get_column('notes', 'service = %s', self[SERVICES], dbtable='service_notes')
        else: service_notes = bacula.get_column('notes', 'service is NULL', dbtable='service_notes')
        if service_notes:
            service_string = '\n'.join(service_notes).replace('\n', self.spacer)
            result.append(self.fmt % ('Service Notes (%s)' % self[SERVICES], service_string))

        return '\n'.join(result)

    # }}}
    # {{{ client_conf():

    def client_conf(self):
        return '''
Client {
  Name = %(hostname)s
  Address = %(address)s
  Catalog = MyCatalog
  Password = %(password)s
  File Retention = %(file_retention)s
  Job Retention = %(job_retention)s
  AutoPrune = yes
}
''' % self

    # }}}
    # {{{ client_device():

    def client_device(self):
        return '''
Device {
  Name = %(hostname)s-%(fileset)s
  Media Type = %(hostname)s-%(fileset)s
  Archive Device = /data/bacula
  LabelMedia = yes;
  Random Access = yes;
  AutomaticMount = yes;
  RemovableMedia = no;
  AlwaysOpen = no;
}
''' % self

    # }}}
    # {{{ client_storage():

    def client_storage(self):
        return '''
Storage {
  Name = %(hostname)s-%(fileset)s
  Address = %(storageserveraddress)s
  SDPort = 9103
  Password = %(storagepassword)s
  Device = %(hostname)s-%(fileset)s
  Media Type = %(hostname)s-%(fileset)s
  Maximum Concurrent Jobs = 1
}
''' % self

    # }}}
    # {{{ client_job():
    
    def client_job(self):
        self['script'] = ''.join([self.script(x) for x in ('begin', 'end', 'failure')])
        return '''
Job {
  Name = %(hostname)s-%(fileset)s
  Client = %(hostname)s
  Enabled = %(enabled)s
  Storage = %(hostname)s-%(fileset)s
  Write Bootstrap = \"%(bootstrapdir)s/%(hostname)s%(fileset)s.bsr\"
  Priority = %(priority)s
  Maximum Concurrent Jobs = 1
  Type = Backup
  Level = Incremental
  FileSet = %(fileset)s
  Schedule = %(schedule)s
  Messages = %(message_set)s
  Pool = %(pool)s
  Rerun Failed Levels = yes
  Allow Mixed Priority = yes
%(script)s
}
''' % self

# }}}
    # {{{ client_verify_job():
    
    def client_verify_job(self):
        if 'Snap' in self[FILESET]: return ''
        return '''
Job {
  Name = %(hostname)s-%(fileset)s-Verify
  Client = %(hostname)s
  Enabled = Yes
  Storage = %(hostname)s-%(fileset)s
  Priority = %(priority)s
  Maximum Concurrent Jobs = 1
  Type = Verify
  Level = VolumeToCatalog
  Verify Job = %(hostname)s-%(fileset)s
  FileSet = %(fileset)s
  Messages = %(message_set)s
  Pool = %(pool)s
  Allow Mixed Priority = yes
}
''' % self

# }}}
    # {{{ script(word):

    def script(self, word):
        s = self[word]
        if not s: return ''
        s = s % self
        sWhen = 'After'
        sFail = 'No'
        sExtra = ''
        if word == 'begin':
            sWhen = 'Before'
            sExtra = "\t\tFailJobOnError = Yes\n"
        if word == 'failure':
            sExtra = "\t\tRunsOnSuccess = No\n"
            sFail = YES
        return "\tRun Script {\n\t\tCommand = \"%(s)s\"\n\t\tRunsWhen = %(sWhen)s\n\t\tRunsOnFailure = %(sFail)s\n\t\tRunsOnClient = Yes\n%(sExtra)s\t}\n" % locals()

# }}}
    # {{{ toggle_enabled(): toggle whether backups are enabled for this client/job

    def toggle_enabled(self):
        new_value = 0
        if self[BACULA_ENABLED] == 0: new_value = 1
        bc = Bacula_Factory()
        sql = 'update %s set bacula_enabled = %%s where hostid = %%s' % HOSTS
        bc.safe_do_sql(sql, (new_value, self[HOSTID]))
        self[BACULA_ENABLED] = new_value
        return

# }}}
    # {{{ change(field, value): Update the value of a field

    def change(self, field, value):
        bc = Bacula_Factory()
        sql = 'update %s set %s = %%s where hostid = %%s' % (HOSTS, field)
        bc.safe_do_sql(sql, (value, self[HOSTID]))
        self[field] = value
        return

# }}}
    # {{{ update_service_notes(text, replace=False): Update the value of a field

    def update_service_notes(self, text, replace=False):
        bc = Bacula_Factory()
        if replace:
            if self[SERVICES]: bc.safe_do_sql('DELETE FROM service_notes WHERE service = %s', self[SERVICES])
            else: bc.safe_do_sql('DELETE FROM service_notes WHERE service IS NULL')
        if not text: return
        sql = 'INSERT INTO service_notes (service, notes) VALUES (%s, %s)'
        for line in text.split('\n'):
            bc.safe_do_sql(sql, (self[SERVICES], line))
        return

# }}}
    # {{{ add_job(args): Add a job instead of updating an existing job.  Default values from the current job

    def add_job(self, args):
        if args.fileset: self[FILESET] = args.fileset
        if args.file_retention: self[FILE_RETENTION] = args.file_retention
        if args.job_retention: self[JOB_RETENTION] = args.job_retention
        if args.notes: self[NOTES] = args.notes
        if args.owners: self[OWNERS] = args.owners
        if args.priority: self[PRIORITY] = args.priority
        if args.schedule: self[SCHEDULE] = args.schedule
        if args.service: self[SERVICES] = args.service
        if args.script_begin: self[BEGIN] = args.script_begin
        if args.script_end: self[END] = args.script_end
        if args.script_fail: self[FAILURE] = args.script_fail
        if args.toggle: self[BACULA_ENABLED] =  1 if self[BACULA_ENABLED] == 0 else 0
        print( self)
        bc = Bacula_Factory()
        sql = '''INSERT INTO bacula_hosts
                 (hostname, address, storageserver, password, fileset,
                  bacula_enabled, priority, schedule, os, notes, db, begin,
                  end, failure, file_retention, job_retention, director,
                  owners, services)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'''
        data = [self[HOSTNAME], self[ADDRESS], self[STORAGESERVER],
                self[PASSWORD], self[FILESET], self[BACULA_ENABLED],
                self[PRIORITY], self[SCHEDULE], self[OS], self[NOTES],
                self[DB], self[BEGIN], self[END], self[FAILURE],
                self[FILE_RETENTION], self[JOB_RETENTION], self[DIRECTOR],
                self[OWNERS], self[SERVICES]
                ]
        try:
            bc.do_sql(sql, data)
            print('New job created for', self[HOSTNAME])
        except:
            print( 'Unable to create the job')
            pass             # This will happen under lots of circumstances

        # }}}
    # {{{ file_daemon_conf(): return the bacula-fd.conf data

    def file_daemon_conf(self):
        retval = []
        bc = Bacula_Factory()
        for d in bc.get_directors():
            retval.append('''Director {
	Name = %s
	Password = "%s"
}
''' % (d[HOSTNAME], self[PASSWORD]))
        self['workdir'] = WORKING_DIR[self[OS]]
        retval.append('''FileDaemon {
	Name = %(hostname)s
	FDport = 9102
	WorkingDirectory = %(workdir)s
	Pid Directory = /var/run
	Maximum Concurrent Jobs = 20
}

Messages {
	Name = Standard
	director = %(director_name)s = all, !skipped, !restored
}
''' % self)
        return '\n'.join(retval)

    # }}}
