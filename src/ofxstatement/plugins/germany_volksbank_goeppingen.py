import csv
from ofxstatement.parser import CsvStatementParser
from ofxstatement.plugin import Plugin
from ofxstatement.statement import BankAccount, StatementLine, \
    generate_stable_transaction_id, check_balance
import re

NEWLINE_ESCAPE = ";"
ABWA = re.compile("ABWA:\s*(.*)$")
IBAN_BIC = re.compile("IBAN:\s*([^\s]*)\s*BIC:\s*([^\s]*)")
EREF_MREF_CRED = re.compile("EREF:\s*(.*)\s*MREF:\s*(.*)\s*CRED:\s*(.*)")

TMAPPINGS = {
    "SB-Auszahlung": (-1, "CASH"),
    "SEPA-Basislastschr.": (-1, "DIRECTDEBIT"),
    "Überweisungsgutschr.": (1, "XFER"),
    "SEPA-Überweisung": (-1, "XFER"),
    "Abschluss": (1, "INT"),
    "Dauerauftrag": (-1, "REPEATPMT"),
    "Gewinnsparen": (-1, "DEBIT"),
    "Lohn/Gehalt/Rente": (1, "XFER")
}


class VolksbankGoeppingenPlugin(Plugin):
    def get_parser(self, filename):
        encoding = self.settings.get('charset', 'iso-8859-1')
        f = open(filename, 'r', encoding=encoding)
        parser = VolksbankGoeppingenParser(f)
        parser.statement.currency = self.settings.get('currency', 'EUR')
        return parser


class VolksbankGoeppingenParser(CsvStatementParser):
    date_format = "%d.%m.%Y"

    def split_records(self):
        return csv.reader(self.fin, delimiter=";")

    def parse_float(self, f):
        # convert a number in german localization (e.g. 1.234,56) into a float
        return float(f.replace('.', '').replace(',', '.'))

    def parse_transaction_info(self, line):
        l = line[8].split("\n")  # get rid of the newlines
        info = dict()

        tm = TMAPPINGS.get(l[0], None)
        if tm is None:
            raise ValueError("cannot determine transfer direction '%r'" % line)

        info["sign"], info["ttype"] = tm

        # mark positions where newlines were
        escaped_text = NEWLINE_ESCAPE.join(l[1:])
        # remove newlines for regex matching
        text = "".join(l[1:])

        # parse remaining text
        m = ABWA.search(text)
        if m is not None:
            info["altpayee"] = m.group(1).strip()
            text, escaped_text = remove_matched(text, escaped_text,
                                                m.start(), m.end())

        m = IBAN_BIC.search(text)
        if m is not None:
            info["iban"] = m.group(1)
            info["bic"] = m.group(2)
            text, escaped_text = remove_matched(text, escaped_text,
                                                m.start(), m.end())

        m = EREF_MREF_CRED.search(text)
        if m is not None:
            info["eref"] = m.group(1).strip()
            info["mref"] = m.group(2).strip()
            info["cred"] = m.group(3).strip()
            text, escaped_text = remove_matched(text, escaped_text,
                                                m.start(), m.end())

        # replaces newlines with spaces in the remaining text
        info["memo"] = "%s: %s" % (l[0],
                                   escaped_text.replace(NEWLINE_ESCAPE, " "))
        return info

    def parse_record(self, line):
        if len(line) < 5:
            return None
        elif len(line) < 12:
            # possibly meta information about the account
            if "BLZ" in line[0]:
                self.statement.bank_id = line[1]
            elif "Konto" in line[0]:
                self.statement.account_id = line[1]

            return None

        if line[9] == "Anfangssaldo":
            self.statement.start_date = self.parse_datetime(line[0])
            self.statement.start_balance = self.parse_float(line[11])
            return None
        elif line[9] == "Endsaldo":
            self.statement.end_date = self.parse_datetime(line[0])
            self.statement.end_balance = self.parse_float(line[11])
            return None
        elif line[0] == "Buchungstag":
            # it's the table header
            return None

        sl = StatementLine()
        sl.date = self.parse_datetime(line[0])
        sl.date_avail = self.parse_datetime(line[1])

        # Note: amount has no sign. We need to guess it later...
        sl.amount = self.parse_float(line[11])

        info = self.parse_transaction_info(line)
        sl.amount *= info["sign"]
        sl.trntype = info["ttype"]

        if "iban" in info:
            # additional bank information if present
            sl.bank_account_to = BankAccount(**self.parse_iban(info["iban"]))

        if line[10] != self.statement.currency:
            # different currency is used
            sl.currency = line[10]

        # remove additional spaces in the payee
        sl.payee = re.sub(' +', ' ', line[3].replace("\n", " ").strip())[:32]

        # remove additional spaces in the memo
        sl.memo = re.sub(' +', ' ', info["memo"].strip())

        # we need to generate an ID because nothing is given
        sl.id = generate_stable_transaction_id(sl)
        return sl

    def parse(self):
        super().parse()
        assert check_balance(self.statement), \
            "Could not guess all transaction directions correctly!"
        return self.statement


def remove_matched(text, escaped_text, start, end):
    estart = start
    idx = start
    eidx = start

    while idx < end and eidx < len(escaped_text):
        # search the string in the escaped_text
        if escaped_text[eidx] == text[idx]:
            eidx += 1
            idx += 1
        elif escaped_text[eidx] == NEWLINE_ESCAPE:
            eidx += 1
        else:
            # mismatch: we need to move start position
            idx = start
            eidx += 1
            estart = eidx

    assert idx == end, "%s - %s [%d,%d)" % (text, escaped_text, start, end)

    return (text[:start] + text[end:],
            escaped_text[:estart] + escaped_text[eidx:])
