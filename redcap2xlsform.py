#!/usr/bin/env python3
"""This module converts redcap form files into XLSForm which can be used
in kobotoolbox.
"""
import csv
import re
import argparse
import zipfile
import os

import xlwt
import html2text


class ColumnToCopyDoesNotExistException(Exception):
    def __init__(self, column):
        Exception.__init__(self, 'Column to copy "{}" does not exist in REDCap file!'.format(column))
        self.column = column


class CrossFormsReferenceException(Exception):
    def __init__(self, message):
        Exception.__init__(self, message)


class NameConverter:
    """Holds variable name from redcap file."""
    def __init__(self, name):
        self.name = name

    def convertToXLS(self):
        """Converts name to XLSForm format and returns it."""
        return self.name


class TypeConverter:
    """Holds variable type from redcap type."""
    convertFromTypeLookup = {'descriptive': 'note', 'notes': 'text', 'calc': 'calculate'}
    convertFromTypeWithChoicesLookup = {'radio': 'select_one ',
                                        'checkbox': 'select_multiple ',
                                        'dropdown': 'select_one '}
    convertFromTypeAndValidationLookup = {'date_dmy': 'date',
                                          'time': 'time',
                                          'number': 'decimal',
                                          'integer': 'integer'}

    incrementListNumber = 1
    leaveListNumber = 0

    def __init__(self, type_, validation):
        self.type_ = type_
        self.validation = validation

    def convertToXLS(self, listNumber):
        """Converts type to XLSForm format and returns it."""
        if self._isYesNo():
            return self._convertYesNo()

        elif self._isConvertableFromType():
            return self._convertFromType()

        elif self._isConvertibleFromTypeWithChoices():
            return self._convertFromTypeWithChoices(listNumber)

        elif self._isConvertibleFromTypeAndValidation():
            return self._convertFromTypeAndValidation()

        else:
            return self._convertTextOrNoMatch()

    def _isYesNo(self):
        return self.type_ == 'yesno'

    def _convertYesNo(self):
        return 'select_one yes_no', self.leaveListNumber

    def _isConvertableFromType(self):
        return self.type_ in self.convertFromTypeLookup

    def _convertFromType(self):
        return self.convertFromTypeLookup[self.type_], self.leaveListNumber

    def _isConvertibleFromTypeWithChoices(self):
        return self.type_ in self.convertFromTypeWithChoicesLookup

    def _convertFromTypeWithChoices(self, listNumber):
        typeBody = self.convertFromTypeWithChoicesLookup[self.type_]
        type_ = typeBody + self._makeListName(listNumber)
        return type_, self.incrementListNumber

    def _makeListName(self, listNumber):
        return 'list_' + str(listNumber)

    def _isConvertibleFromTypeAndValidation(self):
        return self.validation in self.convertFromTypeAndValidationLookup

    def _convertFromTypeAndValidation(self):
        type_ = self.convertFromTypeAndValidationLookup[self.validation]
        return type_, self.leaveListNumber

    def _convertTextOrNoMatch(self):
        return 'text', self.leaveListNumber


class LabelConverter:
    """Holds variable label from redcap file."""
    def __init__(self, label, name):
        self.label = label
        self.name = name

    def convertToXLS(self):
        """Converts label to XLSForm format and returns it."""
        if self.label:
            return self._convertLabel()
        else:
            return self._convertName()

    def _convertLabel(self):
        convertedLabel = html2text.html2text(self.label)
        return convertedLabel

    def _convertName(self):
        return self.name


class ConstraintConverter:
    """Holds information about variable constraints from redcap file."""
    lessThanStr = '(. <= {})'
    greaterThanStr = '(. >= {})'

    def __init__(self, min_, max_):
        self.min_ = min_
        self.max_ = max_

    def convertToXLS(self):
        """Converts constraints information to XLSForm format and returns it."""
        constraint = ''

        if self._existLowerBound():
            constraint = self._addLowerConstraint(constraint)
        if self._existUpperBound():
            constraint = self._addUpperConstraint(constraint)

        return constraint

    def _existLowerBound(self):
        return self.min_

    def _existUpperBound(self):
        return self.max_

    def _addLowerConstraint(self, givenConstraints):
        currentConstraint = self._getLowerConstraint()
        return self._addConstraint(givenConstraints, currentConstraint)

    def _addUpperConstraint(self, givenConstraints):
        currentConstraint = self._getUpperConstraint()
        return self._addConstraint(givenConstraints, currentConstraint)

    def _addConstraint(self, givenConstraints, currentConstraint):
        if givenConstraints:
            return self._addToOneOrMore(givenConstraints, currentConstraint)
        else:
            return self._makeConstraint(currentConstraint)

    def _getLowerConstraint(self):
        return self.greaterThanStr.format(self.min_)

    def _getUpperConstraint(self):
        return self.lessThanStr.format(self.max_)

    def _addToOneOrMore(self, givenConstraints, currentConstraint):
        return givenConstraints + ' and ' + currentConstraint

    def _makeConstraint(self, currentConstraint):
        return currentConstraint


class RelevantConverter:
    """Holds expression from redcap file whether or not to show question."""
    singleVariableRegex = r"\[(\w+)\]\s*([!<>=]{,2})\s*([\'\"]?)(\w*)[\'\"]?"
    singleVariableSubstituteRegex = r"${\1} \2 \3\4\3"
    arrayRegex = r"\[(\w+)\((\w+)\)\]\s*([!=]{,2})\s*[\'\"]?(\w*)[\'\"]?"
    arraySubstitute = "selected('{}','{}')"

    def __init__(self, expression):
        self.expression = expression

    def convertToXLS(self):
        """Converts axpression to XLSForm format and returns it."""
        singleVariablesConverted = re.sub(self.singleVariableRegex,
                                          self.singleVariableSubstituteRegex,
                                          self.expression)

        arraysConverted = self.convertArrays(singleVariablesConverted)

        differentConverted = re.sub(r"<>",
                                    r"!=",
                                    arraysConverted)
        orConverted = re.sub(r"(?i)or",
                             r"or",
                             differentConverted)
        andConverted = re.sub(r"(?i)and",
                              r"and",
                              orConverted)
        allConverted = andConverted
        return allConverted

    def convertArrays(self, text):
        converted = text
        while re.search(self.arrayRegex, converted):
            match = re.search(self.arrayRegex, converted)
            operator = match.group(3)
            value = match.group(4)[-1]  #sometimes values are not just 1 or 0 so we will check only last character
            array = match.group(1)
            item = match.group(2)
            substitute = self.arraySubstitute.format(array, item)
            if (operator == '=' and value == '0') or (operator == '!=' and value == '1'):
                substitute = 'not(' + substitute + ')'
            converted = re.sub(self.arrayRegex,
                                     substitute,
                                     converted,
                                     count = 1)
        return converted


class RequiredConverter:
    """Holds informations whether variable is required."""
    def __init__(self, required):
        self.required = required

    def convertToXLS(self):
        """Converts information to XLSForm format and returns it."""
        if self._isRequired():
            return 'yes'
        else:
            return 'no'

    def _isRequired(self):
        return self.required == 'y'


class ChoicesConverter:
    """Holds information about available choices to question."""
    def __init__(self, type_, choices):
        self.type_ = type_
        if type_ != 'calculate':
            self.choices = self._separateChoices(choices)
            self.listName = self._extractListName(type_)

    def _separateChoices(self, choices):
        if choices:
            return choices.split('|')
        else:
            return []

    def _extractListName(self, type_):
        splittedType = type_.split(' ')
        if len(splittedType) == 2:
            return splittedType[1]
        else:
            return None

    def convertToXLS(self):
        """Converts information to XLSForm format and returns it."""
        if self.type_ != 'calculate':
            convertedChoices = []

            for choice in self.choices:
                convertedChoice = self._convertChoice(choice)
                convertedChoices.append(convertedChoice)

            return convertedChoices

        return []

    def _convertChoice(self, choice):
        name, label = self._splitChoice(choice)
        convertedChoice = XLSChoice(self.listName, name, label)
        return convertedChoice

    def _splitChoice(self, choice):
        if ',' in choice:
            splittedChoice = choice.split(',')
        elif ':' in choice:
            splittedChoice = choice.split(':')
        else:
            raise Exception('Cannot read choice in this format: ' + choice)
        name = splittedChoice[0].strip()
        label = splittedChoice[1].strip()
        return name, label


class CalculationsConverter:
    """Converts calculations from redcap file to XLSForm format."""
    singleVariableRegex = r"\[(\w+)\]"
    singleVariableSubstituteRegex = r"${\1}"
    arrayRegex = r"\[(\w+)\((\w+)\)\]"
    arraySubstituteRegex = r"selected(${\1},'\2')"

    def __init__(self, type_, expression):
        self.type_ = type_
        if type_ == 'calculate':
            self.expression = expression

    def convertToXLS(self):
        """Converts axpression to XLSForm format and returns it."""
        if self.type_ == 'calculate':
            singleVariableConverted = re.sub(self.singleVariableRegex,
                                             self.singleVariableSubstituteRegex,
                                             self.expression)
            singleAndArraysConverted = re.sub(self.arrayRegex,
                                              self.arraySubstituteRegex,
                                              singleVariableConverted)
            return singleAndArraysConverted

        return ''


class DeafultsConverter:
    """Converts default values for questions from redcap file to XLSForm format."""
    defaultsRegex = r"(?i)@default\s*=\s*[\'\"]?([^\'\"]*)[\'\"]?"

    def __init__(self, annotation):
        self.annotation = annotation

    def convertToXLS(self):
        m = re.search(self.defaultsRegex, self.annotation)
        if m and (len(m.groups()) > 0):
            defaultValue = m.group(1)
        else:
            defaultValue = ""

        return defaultValue


class ReadOnlyConverter:
    """Converts hidden values from redcap file to read only in XLSForm format."""
    readOnlyRegex = r"(?i)@hidden"

    def __init__(self, annotation):
        self.annotation = annotation

    def convertToXLS(self):
        if re.search(self.readOnlyRegex, self.annotation):
            readOnly = "yes"
        else:
            readOnly = ""

        return readOnly


class HintsConverter:
    """Converts hints from redcap file to XLSForm format."""
    def __init__(self, hint):
        self.hint = hint

    def convertToXLS(self):
        """Converts hint to XLSForm format and returns it."""
        return self.hint


class XLSChoice:
    """Holds information about available choices to question in XLSForm format."""
    listName = ''
    name = ''
    label = ''

    def __init__(self, listName, name, label):
        self.listName = listName
        self.name = name
        self.label = label


class XLSContent:
    """Holds content of file in XLSForm format."""
    name = ''
    headers = []
    questions = []
    choices = []

    def __init__(self, name, headers, questions, choices):
        self.name = name
        self.headers = headers
        self.questions = questions
        self.choices = choices


class RedcapContent:
    """Holds content of file in redcap format."""
    name = ''
    headers = []
    questions = []

    def __init__(self, name='', headers=[], questions=[]):
        self.name = name
        self.headers = headers
        self.questions = questions


class HeaderConverter:
    """Holds header from redcap file."""
    headersConversionLookup = {'Variable / Field Name': 'name',
                               'Field Type': 'type',
                               'Field Label': 'label',
                               'Text Validation Min': 'constraint',
                               'Branching Logic (Show field only if...)': 'relevant',
                               'Required Field?': 'required',
                               'Field Note': 'hint'}

    def __init__(self, header):
        self.header = header

    def convertToXLS(self):
        """Converts header to XLSForm format and returns it."""
        return self.headersConversionLookup.get(self.header, None)


class Converter:
    """Converts content of redcap file to XLSForm."""
    defaultChoices = [XLSChoice('yes_no', 'yes', 'Yes'),
                      XLSChoice('yes_no', 'no', 'No')]
    defaultHeaders = ['calculation', 'default', 'read_only']

    def __init__(self, fileContent, mode, columnsToCopy):
        self._checkColumnsToCopyExistInHeaders(columnsToCopy, fileContent)
        self.columnsToCopy = columnsToCopy
        if mode == 'zip_xls':
            self.forms = self._separateForms(fileContent)
        else:
            self.forms = [fileContent]

    def convert(self):
        """Converts content of the file to XLSForm format and returns it."""
        converted = []
        for form in self.forms:
            convertedHeaders = self._convertHeaders(form.headers)
            convertedQuestions, convertedChoices = self._convertContent(form.questions, form.headers, convertedHeaders)
            converted.append(XLSContent(form.name,
                                        convertedHeaders,
                                        convertedQuestions,
                                        convertedChoices))

        return converted

    def _separateForms(self, fileContent):
        forms = []
        nameIndex = fileContent.headers.index('Variable / Field Name')
        typeIndex = fileContent.headers.index('Field Type')
        branchIndex = fileContent.headers.index('Branching Logic (Show field only if...)')
        calcIndex = fileContent.headers.index('Choices, Calculations, OR Slider Labels')
        formNameIndex = fileContent.headers.index('Form Name')

        currentName = fileContent.questions[0][formNameIndex]
        currentForm = []
        currentVariables = {}
        for i, row in enumerate(fileContent.questions):
            if row != []:
                formName = row[formNameIndex]
                if formName != currentName and formName != '':
                    forms.append(RedcapContent(currentName, fileContent.headers, currentForm))
                    currentName = formName
                    currentForm = []
                    currentVariables = {}

                variables = self._extractVariables(row[branchIndex])
                if row[typeIndex] == 'calc':
                    variables += self._extractVariables(row[calcIndex])

                for variable in variables:
                    if variable not in currentVariables:
                        printable_row = ', '.join(row)
                        printable_row = repr(printable_row)
                        msg = "Cannot divide into multiple forms, "\
                              "condition/calculation refers to other "\
                              "forms in line {line}:\n{row}"
                        raise CrossFormsReferenceException(msg.format(line=i, row=printable_row))
                currentVariables[row[nameIndex]] = True
                currentForm.append(row)

        forms.append(RedcapContent(currentName, fileContent.headers, currentForm))

        return forms

    def _extractVariables(self, expression):
        singleVariableRegex = r"\[(\w+)\]"
        arrayRegex = r"\[(\w+)\(\w+\)\]"
        variables = re.findall(singleVariableRegex, expression)
        variables += re.findall(arrayRegex, expression)

        return variables

    def _convertHeaders(self, redcapHeaders):
        convertedHeaders = []

        for header in redcapHeaders:
            redcapHeader = HeaderConverter(header)
            convertedHeader = redcapHeader.convertToXLS()
            if convertedHeader:
                convertedHeaders.append(convertedHeader)

        convertedHeaders += self.defaultHeaders
        convertedHeaders += self.columnsToCopy
        return convertedHeaders

    def _convertContent(self, redcapQuestions, redcapHeaders, convertedHeaders):
        convertedQuestions = []
        convertedChoices = []
        listNumber = 0
        listNumbermax = 0
        choiceSets = []
        convertedChoices += self.defaultChoices
        prevGroups = 0

        for i, row in enumerate(redcapQuestions):
            if not row:
                continue

            if row[redcapHeaders.index('Section Header')]:
                if prevGroups > 0:
                    convertedQuestions.append(self._endGroup(convertedHeaders))
                convertedQuestions.append(self._beginGroup(convertedHeaders, prevGroups, row[redcapHeaders.index('Section Header')]))
                prevGroups += 1

            redcapRow = RowConverter(row, redcapHeaders,
                                     convertedHeaders, listNumber,
                                     self.columnsToCopy)
            questions, choices, listIncrement = redcapRow.convertToXLS()

            if len(choices) > 0:
                namesFromSet = sorted([c.name for c in choices])
                if namesFromSet not in choiceSets:
                    listNumber = listNumbermax
                    listNumbermax += listIncrement
                else:
                    listNumber = choiceSets.index(namesFromSet)

            redcapRow = RowConverter(row, redcapHeaders,
                                     convertedHeaders, listNumber,
                                     self.columnsToCopy)
            questions, choices, listIncrement = redcapRow.convertToXLS()

            if questions:
                convertedQuestions.append(questions)

            if len(choices) > 0:
                if namesFromSet not in choiceSets:
                    choiceSets.append(namesFromSet)
                    convertedChoices += choices

        if prevGroups > 0:
            convertedQuestions.append(self._endGroup(convertedHeaders))

        return convertedQuestions, convertedChoices

    def _beginGroup(self, headers, prevGroups, label):
        groupBegin = [''] * len(headers)
        groupBegin[headers.index('name')] = 'group_' + str(prevGroups + 1)
        groupBegin[headers.index('label')] = label
        groupBegin[headers.index('type')] = 'begin group'
        return groupBegin

    def _endGroup(self, headers):
        groupEnd = [''] * len(headers)
        groupEnd[headers.index('type')] = 'end group'
        return groupEnd

    def _checkColumnsToCopyExistInHeaders(self, columns, fileContent):
        for column in columns:
            if not column in fileContent.headers:
                raise ColumnToCopyDoesNotExistException(column)


class RowConverter:
    """Holds information about single row from redcap file."""
    def __init__(self, row, redcapHeaders, convertedHeaders, listNumber, columnsToCopy):
        self.row = row
        self.redcapHeaders = redcapHeaders
        self.convertedHeaders = convertedHeaders
        self.listNumber = listNumber
        self.columnsToCopy = columnsToCopy
        self._processHeaders()
        self._processValues()

    def _processHeaders(self):
        self.redcapHeaderIndex = {}
        self.XLSHeaderIndex = {}

        for i, header in enumerate(self.redcapHeaders):
            self.redcapHeaderIndex[header] = i

        for i, header in enumerate(self.convertedHeaders):
            self.XLSHeaderIndex[header] = i

    def _processValues(self):
        self.name = self._getRedcapVal('Variable / Field Name')
        self.type_ = self._getRedcapVal('Field Type')
        self.validation = self._getRedcapVal('Text Validation Type OR Show Slider Number')
        self.label = self._getRedcapVal('Field Label')
        self.lowerBound = self._getRedcapVal('Text Validation Min')
        self.upperBound = self._getRedcapVal('Text Validation Max')
        self.relevant = self._getRedcapVal('Branching Logic (Show field only if...)')
        self.required = self._getRedcapVal('Required Field?')
        self.choicesOrCalculations = self._getRedcapVal('Choices, Calculations, OR Slider Labels')
        self.annotation = self._getRedcapVal('Field Annotation')
        self.hint = self._getRedcapVal('Field Note')
        self.additional = {column: self._getRedcapVal(column) for column in self.columnsToCopy}

    def convertToXLS(self):
        """Converts row to XLSForm format and returns it."""
        self.convertedRow = [''] * len(self.convertedHeaders)

        if not self._isEmpty():
            if self._hasXLSHeader('name'):
                self._convertName()

            if self._hasXLSHeader('type'):
                self._convertType()

            if self._hasXLSHeader('label'):
                self._convertLabel()

            if self._hasXLSHeader('constraint'):
                self._convertConstraint()

            if self._hasXLSHeader('relevant'):
                self._convertRelevant()

            if self._hasXLSHeader('required'):
                self._convertRequired()

            if self._hasXLSHeader('hint'):
                self._convertHint()

            self._convertChoices()
            self._convertCalculations()
            self._convertDefaults()
            self._convertReadOnly()
            self._convertAdditional()
        else:
            self.convertedRow = ''
            self.convertedChoices = []
            self.listIncrement = 0

        return self.convertedRow, self.convertedChoices, self.listIncrement

    def _convertName(self):
        redcapName = NameConverter(self.name)
        convertedName = redcapName.convertToXLS()
        self._setXLSVal('name', convertedName)

    def _convertType(self):
        redcapType = TypeConverter(self.type_, self.validation)
        convertedType, increment = redcapType.convertToXLS(self.listNumber)
        self.convertedType = convertedType
        self._setXLSVal('type', convertedType)
        self.listIncrement = increment

    def _convertLabel(self):
        redcapLabel = LabelConverter(self.label, self.name)
        convertedLabel = redcapLabel.convertToXLS()
        self._setXLSVal('label', convertedLabel)

    def _convertConstraint(self):
        redcapConstraint = ConstraintConverter(self.lowerBound, self.upperBound)
        convertedConstraint = redcapConstraint.convertToXLS()
        self._setXLSVal('constraint', convertedConstraint)

    def _convertRelevant(self):
        redcapRelevant = RelevantConverter(self.relevant)
        convertedRelevant = redcapRelevant.convertToXLS()
        self._setXLSVal('relevant', convertedRelevant)

    def _convertRequired(self):
        redcapRequired = RequiredConverter(self.required)
        convertedRequired = redcapRequired.convertToXLS()
        self._setXLSVal('required', convertedRequired)

    def _convertCalculations(self):
        redcapCalculations = CalculationsConverter(self.convertedType, self.choicesOrCalculations)
        convertedCalculations = redcapCalculations.convertToXLS()
        self._setXLSVal('calculation', convertedCalculations)

    def _convertDefaults(self):
        redcapDefaults = DeafultsConverter(self.annotation)
        convertedDeafults = redcapDefaults.convertToXLS()
        self._setXLSVal('default', convertedDeafults)

    def _convertReadOnly(self):
        redcapReadOnly = ReadOnlyConverter(self.annotation)
        convertedReadOnly = redcapReadOnly.convertToXLS()
        self._setXLSVal('read_only', convertedReadOnly)

    def _convertHint(self):
        redcapHint = HintsConverter(self.hint)
        convertedHint = redcapHint.convertToXLS()
        self._setXLSVal('hint', convertedHint)

    def _convertAdditional(self):
        for column in self.additional:
            self._setXLSVal(column, self.additional.get(column))

    def _convertChoices(self):
        redcapChoices = ChoicesConverter(self.convertedType, self.choicesOrCalculations)
        self.convertedChoices = redcapChoices.convertToXLS()

    def _hasXLSHeader(self, header):
        return header in self.convertedHeaders

    def _getRedcapVal(self, header):
        index = self._getRedcapIndex(header)
        if index < len(self.row):
            return self.row[index]
        else:
            return ''

    def _setXLSVal(self, header, value):
        index = self._getXLSIndex(header)
        self.convertedRow[index] = value

    def _getRedcapIndex(self, type_):
        return self.redcapHeaderIndex.get(type_)

    def _getXLSIndex(self, type_):
        return self.XLSHeaderIndex.get(type_)

    def _isEmpty(self):
        redcapName = NameConverter(self.name)
        convertedName = redcapName.convertToXLS()
        return not convertedName


class XLSWriter:
    """Writes content in XLSForm format to a file."""
    def __init__(self, filename, mode):
        self.path = os.path.dirname(filename)
        self.path += '/'
        self.filename = filename
        self.mode = mode

    def write(self, content):
        """Writes content in XLSForm format to a file."""
        if self.mode == "single_xls":
            self._writeFile(self.filename, content[0])
        else:
            with zipfile.ZipFile(self.filename, 'w') as file:
                for form in content:
                    self._writeFile(form.name + '.xls', form)
                    file.write(form.name + '.xls')
                    os.remove(form.name + '.xls')

    def _writeFile(self, filename, content):
        book = xlwt.Workbook()
        surveySheet = book.add_sheet('survey')
        choicesSheet = book.add_sheet('choices')
        self._writeSurvey(surveySheet, content.headers, content.questions)
        self._writeChoices(choicesSheet, content.choices)
        book.save(filename)

    def _writeSurvey(self, sheet, headers, questions):
        self._writeRow(0, headers, sheet)

        for i, row in enumerate(questions):
            self._writeRow(i + 1, row, sheet)

    def _writeChoices(self, sheet, choices):
        choicesHeaders = ['list name', 'name', 'label']
        self._writeRow(0, choicesHeaders, sheet)

        for i, choice in enumerate(choices):
            sheet.write(i + 1, 0, choice.listName)
            sheet.write(i + 1, 1, choice.name)
            sheet.write(i + 1, 2, choice.label)

    def _writeRow(self, rowNumber, row, sheet):
        for j, item in enumerate(row):
            sheet.write(rowNumber, j, item)


def readRedcapFile(filename):
    """Reads content of the redcap file and returns it."""
    content = RedcapContent()

    with open(filename, newline='', encoding='utf-8-sig') as file:
        reader = csv.reader(file)

        for i, row in enumerate(reader):
            if i == 0:
                content.headers = row
            else:
                content.questions.append(row)

    return content


def parseArgs():
    """Returns name of file to convert and name of file to write result to."""
    ext_from_mode = {'zip_xls': '.zip', 'single_xls': '.xls'}
    argParser = argparse.ArgumentParser()
    argParser.add_argument("filename")
    argParser.add_argument("-s", "--savefile",
                           help="Name of converted file. If not specified, " +
                                "then name is the same as input file")
    argParser.add_argument("-m", "--mode",
                           help="Mode of conversion:\n" +
                           "zip_xls - creates new file for each form name in file (default)\n" +
                           "single_xls - creates single file with all forms in it")
    argParser.add_argument("-c", "--copycolumn",
                           nargs='*',
                           help="Select additional columns to copy to converted file")
    args = argParser.parse_args()

    filename = args.filename

    mode = 'zip_xls'
    if args.mode:
        mode = args.mode

    if args.savefile:
        savefile = args.savefile
    else:
        savefile = os.path.splitext(filename)[0]
        savefile += ext_from_mode[mode]

    columnsToCopy = []
    if args.copycolumn:
        columnsToCopy = args.copycolumn

    return filename, savefile, mode, columnsToCopy


if __name__ == "__main__":
    filename, savefile, mode, columnsToCopy = parseArgs()

    fileContent = readRedcapFile(filename)

    try:
        convertedContent = Converter(fileContent, mode, columnsToCopy).convert()
        XLSWriter(savefile, mode).write(convertedContent)
    except CrossFormsReferenceException as e:
        msg = e.args[0]
        print(msg)
        exit(1)
    except ColumnToCopyDoesNotExistException as e:
        msg = e.args[0]
        print(msg)
        exit(2)
    except Exception as e:
        msg = e.args[0]
        print(msg)
        exit(2)
