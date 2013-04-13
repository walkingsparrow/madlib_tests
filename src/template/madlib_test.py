'''
MADlibTemplateTestCase is a subclass of GPDBTestCase that provides basic 
cababilities to run a templated SQL statement with substitution rules.

For any list parameters passed as "template_vars" it will iterate through 
all combinations
of parameters and generate a separate test case for each combination.
'''

from src.template.sql import MADlibSQLTestCase
from src.test_utils.get_dbsettings import get_dbsettings
from src.test_utils.utils import call_R_script
from tinctest import TINCTestLoader
from tinctest.lib import PSQL, Gpdiff
import new
import os
import re
import sys
import shutil

# ------------------------------------------------------------------------
# Use environment variables to control the behavior:
#
# CREATE_CASE   to create case files
# CREATE_ANS    to create answer files (mainly for input test cases)
# DB_CONFIG     to pick a database configuration from settings.dbsettings
# ------------------------------------------------------------------------

class MADlibTestCase (MADlibSQLTestCase):
    """
    Abstract class for running templated SQL, subclasses must define the template
    """
    # The following variables should be provided by subclass
    schema_madlib   = "madlib"
    schema_testing  = "madlibtestdata"
    sql_dir         = "sql" # store the sql command executed
    out_dir         = "result" # output folder
    ans_dir         = "expected" # expected results
    template        = None  
    template_method = None # method name, controls the file name 
    template_doc    = ""    
    template_vars   = {}
    skip_file = "skip.py"
    skip = []
    _create_ans = False
    _create_case = False
    _db_settings = dict(dbname = None, username = None, userpwd = None,
                        schema_madlib = "madlib",
                        schema_testing = "madlibtestdata",
                        host = None, port = None) # default values
    reserved_keywords = ["_incr", "schema_madlib", "schema_testing"]

    # If you want to use fiel names like "linregr_input_test_{incr}",
    # increse incr for every test, which is done in the super class
    # This number is used for file name
    # to avoid putting very long arguments in the file name
    _incr = 0 # name is hard-coded

    # -----------------------------------------------------------------

    @classmethod
    def _get_env_flag (cls, flag):
        """
        Get the environment variable for
        creating case or answer file
        """
        if os.environ.has_key(flag):
            value = os.environ.get(flag).lower()
            if (value == "t" or value == "true" or
                value == "yes" or value == "y"):
                return True
        return False

    # -----------------------------------------------------------------

    @classmethod
    def _get_ext_ans (cls, flag, create_ans):
        """
        Get the environment variable for
        creating answer file using
        external script, which takes in
        parameters and compute the results
        """
        if os.environ.has_key(flag):
            if not create_ans:
                print("""
                      MADlib Test Error: R_ANS list only plays an role
                      when CREATE_ANS=T.
    
                      When CREATE_ANS=T and R_ANS=R_script_path, the R
                      script will be executed using the parameters passed
                      from test executor to create results.
                      """)
                sys.exit(1)
                
            value = os.environ.get(flag)
            return (True, value)
        return (False, None)

    # ----------------------------------------------------------------

    @classmethod
    def _validate_vars (cls, template_vars, keywords):
        """
        To ensure that the usre provided template_vars
        does not contain the keywords
        """
        anyMatch = any(key in keywords for key in template_vars.keys())
        if anyMatch:
            print("MADlib Test Error: template_vars should not use any of the following keywords:")
            print(keywords)
            sys.exit("Testcase is stopping for " + cls.__name__ + "!")
        return None

    # ----------------------------------------------------------------

    @classmethod
    def _get_skip (cls, skip_file, module_name, create_case):
        """
        Get skip list
        """            
        do_skip_err = False
        if os.environ.has_key("SKIP"):
            if create_case is False:
                print("""
                      MADlib Test Error: SKIP list only plays an role
                      when CREATE_CASE=T.
    
                      The skip-tag will be added to the head of each test case
                      file when it is created. During execution, all files with
                      skip-tag at the beginning of it will be skipped.
                      """)
                sys.exit(1)

            value = os.environ.get("SKIP")
            m = re.match(r"^(.+)\.([^\.]+)$", value)
            if m is None: # value is just a dict name
                if os.path.exists("./" + skip_file): # check current path
                    ms = os.path.splitext(skip_file)[0]
                else:
                    s = os.path.basename(skip_file)
                    s = os.path.splitext(s)[0]
                    mm = re.match(r"^(.+)\.([^\.]+)$", module_name)
                    if mm is None:
                        ms = module_name + "." + s
                    else:
                        ms = mm.group(1) + "." + s
                try:
                    md = __import__(ms, fromlist = '1')
                    user_skip = getattr(md, value)
                except:
                    do_skip_err = True
            else:
                try:
                    md = __import__(m.group(1), fromlist = '1')
                    user_skip = getattr(md, m.group(2))
                except:
                    do_skip_err = True
        else:
            user_skip = []

        if do_skip_err: # something went wrong
            print("""
                  MADlib Test Error: No such skip definitions for """
                  + cls.__name__ + """!
                  
                  Either you explicitly define the class variable skip_file in
                  you test case class, or you put the skip list into the default
                  skip file skip.py.

                  The environment variable SKIP can have value like:
                  SKIP=examples.linregr_skip.skip_all, which will override
                  the skip_file,
                  or
                  just SKIP=skip_all, and we will search for the skip list in
                  skip_file
                  """)
            sys.exit(1)
        return user_skip        
 
    # ----------------------------------------------------------------

    @classmethod
    def _write_params (cls, f, reserved_keywords, args):
        """
        Write test parameters into the test case file
        """
        for key in args.keys():
            if (key not in reserved_keywords and
                isinstance(args[key], str)):
                f.write("-- @madlib-param " + key + " = \""
                        + args[key] + "\"\n")
        return None

    # ----------------------------------------------------------------
    
    @classmethod
    def loadTestsFromTestCase (cls):
        """
        @param cls The child class 
        """
        # Ensure we pickup the variables from our child class
        template        = cls.template
        template_method = cls.template_method
        template_doc    = cls.template_doc
        template_vars   = cls.template_vars
       
        cls._create_case = MADlibTestCase._get_env_flag("CREATE_CASE")
        cls._create_ans = MADlibTestCase._get_env_flag("CREATE_ANS")
        (r_ans, r_script) = MADlibTestCase._get_ext_ans("R_ANS", cls._create_ans)
        
        # validate cls template_vars
        MADlibTestCase._validate_vars(template_vars,
                                      MADlibTestCase.reserved_keywords)
        
        cls._db_settings = get_dbsettings()
        template_vars.update(schema_madlib = cls._db_settings["schema_madlib"],
                             schema_testing = cls._db_settings["schema_testing"])
        skip_file = cls.skip_file
        skip = MADlibTestCase._get_skip(skip_file, cls.__module__,
                                        cls._create_case)
            
        # XXX: I'm not completely clear why this is necessary, somehow the loadTests ends up
        # being called twice, once for the child class and once from here.  When called from
        # here we need to not die...
        if template is None:
            return []

        assert isinstance(template,str)
        assert isinstance(template_method,str)

        print "loading tests from test case"

        source_file = sys.modules[cls.__module__].__file__
        source_dir = os.path.dirname(os.path.abspath(source_file))
 
        # ------------------------------------------------
        # Also create our "Template" test cases
        def makeTest (x):
            cls._incr += 1
            x["_incr"] = cls._incr
            methodName = TINCTestLoader.testMethodPrefix + template_method.format(**x)
            methodDoc  = template_doc.format(**x)
            methodQuery = template.format(**x)

            ## Skip a test case
            add_flag = True
            for case in skip:
                eq = True
                for key in case.keys():
                    if x[key].lower() != case[key].lower():
                        eq = False
                        break
                if eq:
                    add_flag = False
                    break

            # Create the SQL test case file that we are going to run
            sql_inputfile = os.path.join(source_dir, cls.sql_dir,
                                         methodName + ".sql")
            with open(sql_inputfile, 'w') as f:
                if add_flag is False:
                    f.write("-- @skip Skip this test\n")
                print(methodName + " ............ test case file created")
                MADlibTestCase._write_params(f, MADlibTestCase.reserved_keywords, x)
                f.write("\n")
                f.write(methodQuery)

            # Call external script to compute the result
            # right now, only support R
            # But it is very easy to add support for other softwares
            if r_ans:
                ans_path = os.path.join(source_dir, ans_dir)
                if os.path.exists(r_script):
                    call_R_script(r_script, ans_path, methodName, x)
                else:
                    r_path = os.path.join(source_dir, ans_dir, r_script)
                    call_R_script(r_path, ans_path, methodName, x)
                
        # ------------------------------------------------
        # create test case files
        if cls._create_case:
            makeTestClosure = makeTest
    
            kwargs = {}
            for key, value in template_vars.iteritems():
                if not isinstance(value, list) or key == "skip":
                    kwargs[key] = value
                else:
                    def makefunc (key, values, f):
                        def doit (k):
                            for v in values:
                                k[key] = v
                                f(k)
                        return doit
                    makeTestClosure = makefunc(key, value, makeTestClosure)
                    
            makeTestClosure(kwargs)

        if ((not cls._create_case) or
            (cls._create_ans and (not r_ans))): # if R has already created answers, stop
            # read files to create test cases
            return super(MADlibTestCase, cls).loadTestsFromTestCase()
        else:
            return []

    # ----------------------------------------------------------------
        
    def __init__ (self, methodName):
        super(MADlibTestCase, self).__init__(methodName)

    # ----------------------------------------------------------------
        
    def _run_test (self, sql_file, ans_file):
        """
        (1) Create a SQL wcript for the query
        (2) Run the SQL script using psql to produce the result file
        (3) Compare the result file to the expected answer file
        """
        sql_resultfile = os.path.join(self.get_out_dir(),
                                      os.path.basename(sql_file) + ".out")

        # create the output of SQL script
        db = self.__class__._db_settings
        PSQL.run_sql_file(sql_file, out_file = sql_resultfile,
                          dbname = db["dbname"],
                          username = db["username"],
                          password = db["userpwd"],
                          host = db["host"],
                          port = db["port"])

        # First run to create the baseline file
        if self.__class__._create_ans:
            shutil.copyfile(sql_resultfile, ans_file)
            os.remove(sql_resultfile)
            print "Answer file was created"
            return True

        return self.validate(sql_resultfile, ans_file)
 
    # ----------------------------------------------------------------

    def validate (self, sql_resultfile, answerfile):
        # Check that the answer file exists
        self.assertTrue(os.path.exists(answerfile))

        # Compare actual result to the answer
        return Gpdiff.are_files_equal(sql_resultfile, answerfile)


        
