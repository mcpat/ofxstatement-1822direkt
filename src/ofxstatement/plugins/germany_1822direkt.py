from ofxstatement.plugin import Plugin
from ofxstatement.parser import CsvStatementParser
from ofxstatement.statement import BankAccount, StatementLine

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

    def parse_float(self, f):
        # convert a number in german localization (e.g. 1.234,56) into a float
        return float(f.replace('.', '').replace(',', '.'))

    def parse_record(self, line):
        # FIXME: add header validation
        #print(self.cur_record, line)
        if self.cur_record < 2:
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
        sl.amount = self.parse_float(line[4])
        sl.trntype = TMAPPINGS.get(line[5], 'DEBIT' if sl.amount < 0 else 'CREDIT')
        sl.payee = line[7]
        sl.memo = " ".join(x for x in line[15:33] if len(x) > 0)

        if len(line[8]) > 0 and len(line[9]) > 0:
            # additional bank information if present
            sl.bank_account_to = BankAccount(line[9], line[8])

        return sl
