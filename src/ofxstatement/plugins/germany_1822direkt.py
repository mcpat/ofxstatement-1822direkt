import csv

from ofxstatement.plugin import Plugin
from ofxstatement.parser import CsvStatementParser
from ofxstatement.statement import BankAccount, StatementLine,\
    recalculate_balance

TMAPPINGS = {
    "20005": "CASH",
    "20032": "PAYMENT",
    "20080": "PAYMENT",
    "20200": "DIRECTDEBIT",
    "21050": "XFER",
    "21094": "XFER",
    "25100": "FEE"
}


class FrankfurterSparkasse1822Plugin(Plugin):
    def get_parser(self, filename):
        encoding = self.settings.get('charset', 'iso-8859-1')
        f = open(filename, 'r', encoding=encoding)
        parser = FrankfurterSparkasse1822Parser(f)
        parser.statement.bank_id = self.settings.get('bank', '50050201')
        parser.statement.currency = self.settings.get('currency', 'EUR')
        return parser


class FrankfurterSparkasse1822Parser(CsvStatementParser):
    date_format = "%d.%m.%Y"

    def split_records(self):
        return csv.reader(self.fin, delimiter=';')

    def parse_float(self, f):
        # convert a number in german localization (e.g. 1.234,56) into a float
        return float(f.replace('.', '').replace(',', '.'))

    def parse_record(self, line):
        if line[0] == "Kontonummer":
            # it's the table header
            return None

        if len(line) < 3:
            """e.g.: ['# 1 vorgemerkte Umsätze nicht angezeigt']"""
            return None
        if not line[2]:
            return None

        if self.statement.account_id is None:
            self.statement.account_id = line[0]

        sl = StatementLine()
        sl.id = line[1]
        sl.date = self.parse_datetime(line[2])
        sl.date_avail = self.parse_datetime(line[3])
        sl.amount = self.parse_float(line[4])
        sl.trntype = TMAPPINGS.get(line[5],
                                   'DEBIT' if sl.amount < 0 else 'CREDIT')
        sl.payee = line[7][:32]
        sl.memo = "%s: %s" % (line[6],
                              " ".join(x for x in line[13:31] if len(x) > 0))

        if len(line[8]) > 0 and len(line[9]) > 0:
            # additional bank information is present
            splitted = self.parse_iban(line[8])
            if splitted:
                sl.bank_account_to = BankAccount(**splitted)
            else:
                sl.bank_account_to = BankAccount(line[9], line[8])

        return sl

    def parse(self):
        super().parse()
        recalculate_balance(self.statement)
        return self.statement
