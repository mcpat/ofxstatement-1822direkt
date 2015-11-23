import csv
from ofxstatement.parser import CsvStatementParser
from ofxstatement.plugin import Plugin
from ofxstatement.statement import BankAccount, StatementLine, \
    generate_stable_transaction_id
import re


MT940_EREF = re.compile("EREF\+(.+?)(?:MREF|CRED|SVWZ)")
MT940_MREF = re.compile("MREF\+(.+?)(?:EREF|CRED|SVWZ)")
MT940_CRED = re.compile("CRED\+(.+?)(?:EREF|MREF|SVWZ)")
MT940_SVWZ = re.compile("(?:SVWZ\+)(.+?)(?:ABWA)|(?:SVWZ\+)(.+?)$")
MT940_ABWA = re.compile("ABWA\+(.+)$")

TMAPPINGS = {
    "AUSZAHLUNG": "CASH",
    "GELDAUTOMAT": "CASH",
    "KARTENZAHLUNG": "PAYMENT",
    "LASTSCHRIFT": "DIRECTDEBIT",
    "UEBERTRAG": "XFER",
    "UEBERWEISUNG": "XFER",
    "ENTGELTABSCHLUSS": "FEE",
    "DAUERAUFTRAG": "REPEATPMT"
}


class BerlinerSparkassePlugin(Plugin):
    def get_parser(self, filename):
        encoding = self.settings.get('charset', 'iso-8859-1')
        f = open(filename, 'r', encoding=encoding)
        parser = BerlinerSparkasseParser(f)
        parser.statement.bank_id = self.settings.get('bank', '10050000')
        parser.statement.currency = self.settings.get('currency', 'EUR')
        return parser


class BerlinerSparkasseParser(CsvStatementParser):
    # two different CSV formats:
    # * CSV-MT940 with 11 columns
    # * CSV-CAMT with 17 columns

    mt940_mappings = {"accid": 0,
                      "date": 2,  # valuta date
                      "btext": 3,
                      "payee": 5,
                      "toaccid": 6,
                      "tobankid": 7,
                      "amount": 8,
                      "currency": 9}

    camt_mappings = {"accid": 0,
                     "date": 2,  # valuta date
                     "btext": 3,
                     "payee": 11,
                     "toaccid": 12,
                     "tobankid": 13,
                     "amount": 14,
                     "currency": 15}

    date_format = "%d.%m.%y"

    def split_records(self):
        return csv.reader(self.fin, delimiter=";")

    def parse_float(self, f):
        # convert a number in german localization (e.g. 1.234,56) into a float
        return float(f.replace('.', '').replace(',', '.'))

    def parse_transaction_type(self, amount, text):
        for pattern, ttype in TMAPPINGS.items():
            if pattern in text:
                return ttype

        return 'DEBIT' if amount < 0 else 'CREDIT'

    def parse_transaction_info_mt940(self, line):
        #  re.sub(' +', ' ', line[line["memo"]])
        info = dict()

        m = MT940_EREF.search(line[4])
        if m is not None:
            info["eref"] = m.group(1)

        m = MT940_MREF.search(line[4])
        if m is not None:
            info["mref"] = m.group(1)

        m = MT940_CRED.search(line[4])
        if m is not None:
            info["cred"] = m.group(1)

        m = MT940_SVWZ.search(line[4])
        if m is not None:
            info["memo"] = m.group(1) if m.group(1) is not None else m.group(2)

        m = MT940_ABWA.search(line[4])
        if m is not None:
            info["altpayee"] = m.group(1)

        if "memo" not in info:
            if len(info) == 0:
                info["memo"] = line[4]
            else:
                info["memo"] = ""

        return info

    def parse_transaction_info_camt(self, line):
        info = dict()
        info["memo"] = line[4]

        if len(line[7]) > 0:
            info["eref"] = line[7]

        if len(line[6]) > 0:
            info["mref"] = line[6]

        if len(line[5]) > 0:
            info["cred"] = line[5]

        return info

    def parse_record(self, line):
        if self.cur_record < 2:
            return None

        m = None
        parse_info = None

        if len(line) == 11:
            m = self.mt940_mappings
            parse_info = self.parse_transaction_info_mt940
        elif len(line) == 17:
            m = self.camt_mappings
            parse_info = self.parse_transaction_info_camt
        else:
            raise ValueError("invalid input line: '%s'" % line)

        if self.statement.account_id is None:
            self.statement.account_id = line[m["accid"]]

        sl = StatementLine()
        sl.date = self.parse_datetime(line[m["date"]])
        sl.amount = self.parse_float(line[m["amount"]])
        sl.trntype = self.parse_transaction_type(sl.amount,
                                                 line[m["btext"]])

        # remove leading or all) zeros
        line[m["toaccid"]] = line[m["toaccid"]].lstrip('0')

        if len(line[m["toaccid"]]) > 0 and len(line[m["tobankid"]]) > 0:
            # additional bank information if present
            sl.bank_account_to = BankAccount(line[m["tobankid"]],
                                             line[m["toaccid"]])

        if line[m["currency"]] != self.statement.currency:
            # different currency is used
            sl.currency = line[m["currency"]]

        # remove additional spaces in the payee
        sl.payee = re.sub(' +', ' ', line[m["payee"]])

        info = parse_info(line)
        # remove additional spaces in the memo
        sl.memo = re.sub(' +', ' ', info["memo"].strip())

        # we need to generate an ID because nothing is given
        sl.id = generate_stable_transaction_id(sl)
        return sl
