import scraperwiki
import mechanize
import lxml.etree, lxml.html
import datetime
import re
import urlparse
import cgi

lotterygrantsurl = "http://www.lottery.culture.gov.uk/AdvancedSearch.aspx"


def Main():
    try:
        sminmaxdates = scraperwiki.sqlite.execute("select min(`Grant date`), max(`Grant date`) from swdata").get("data")[0]
    except scraperwiki.sqlite.NoSuchTableSqliteError:
        sminmaxdates = (datetime.date.today().isoformat(), datetime.date.today().isoformat())

    # ten day overlap
    topdate = datetime.datetime.strptime(sminmaxdates[1], "%Y-%m-%d").date() - datetime.timedelta(20)
    botdate = min(datetime.datetime.strptime(sminmaxdates[0], "%Y-%m-%d").date() + datetime.timedelta(10), topdate)
    print topdate, botdate
    
    for i in range(1000):
        topdate1 = min(topdate + datetime.timedelta(1), datetime.date.today())
        if topdate1 != topdate:        
            ScrapeLottery(topdate, topdate1)
            topdate = topdate1
        botdate1 = botdate - datetime.timedelta(1)
        if botdate1 > datetime.date(1997, 1, 1):
            ScrapeLottery(botdate1, botdate)
            botdate = botdate1


def ScrapeLottery(datefrom, dateto):
    br = mechanize.Browser()
    br.set_handle_robots(False)

    response = br.open(lotterygrantsurl)
    br.select_form(name="aspnetForm")
    br["ctl00$phMainContent$dropDownAwardDate"] = ["Between"]
    br["ctl00$phMainContent$txtGrantDateFrom"] = datefrom.strftime("%d/%m/%Y")
    br["ctl00$phMainContent$txtGrantDateTo"]  = (dateto - datetime.timedelta(1)).strftime("%d/%m/%Y")  # make not inclusive
    br["ctl00$phMainContent$dropDownRecordsPerPage"] = ["500"]


    response = br.submit()
    root = lxml.html.fromstring(response.read())
    ngrants = int(root.cssselect("#ctl00_phMainContent_grantSearchResults_labelResultsCount")[0].text)
    print "Scraping", datefrom, dateto, "ngrants", ngrants
    if ngrants == 0:
        assert not root.cssselect("table#ctl00_phMainContent_grantSearchResults_gridViewResults tr")
        return

    # pagenation is actually knackered and always misses out the last page, so we need to do day by day
    # eg 2010-05-11 has 945 grants on it, so it's difficult to thin down

    page = 1
    ngrantscount = 0

    while True:
        rows = root.cssselect("table#ctl00_phMainContent_grantSearchResults_gridViewResults tr")
        headers =[ th.text_content().strip()  for th in rows[0] ]
        assert headers == ['Recipient', 'Project description', u'Grant amount (\xa3)', 'Grant date', 'Local authority', 'Distributing body'], headers
        headers[2] = 'Grant amount'
        ldata = [ ]
        for row in rows[1:]:
            data = dict(zip(headers, [ td.text_content().strip()  for td in row ]))
            #print row[0][0].attrib.get("href")
            data['link'] = urlparse.urljoin(br.geturl(), row[0][0].attrib.get("href"))
            assert data['Grant amount'][0] == u'\xa3'
            data['Grant amount'] = int(re.sub(",", "", data["Grant amount"][1:]))
            mdate = re.match('(\d\d)/(\d\d)/(\d\d\d\d)', data["Grant date"])
            assert mdate, data
            data["Grant date"] = datetime.date(int(mdate.group(3)), int(mdate.group(2)), int(mdate.group(1)))
            qs = data['link'].split('?', 1)[1]
            qsd = dict(cgi.parse_qsl(qs))
            data["DBID"] = qsd["DBID"]
            data["ID"] = qsd["ID"]
            ldata.append(data)
        scraperwiki.sqlite.save(['link'], ldata)
        ngrantscount += len(ldata)

        # next page link
        br.select_form(name="aspnetForm")
        if 'ctl00$phMainContent$grantSearchResults$nextPage' not in [c.name  for c in br.form.controls]:
            if root.cssselect("#ctl00_phMainContent_grantSearchResults_labelPageNumber"):
                pagenumbers = root.cssselect("#ctl00_phMainContent_grantSearchResults_labelPageNumber")[0].text
                mpagenumbers = re.match("page (\d+) of (\d+)", pagenumbers)
                if datefrom.isoformat() in ['2012-05-08', '2012-06-06', '2012-07-23', '2012-08-21']:
                    print "skipping problem assert", datefrom, (pagenumbers, page)
                else:
                    assert int(mpagenumbers.group(2)) == page, (datefrom, pagenumbers, page)
            else:
                assert page == 1
            break

        pagenumbers = root.cssselect("#ctl00_phMainContent_grantSearchResults_labelPageNumber")[0].text
        mpagenumbers = re.match("page (\d+) of (\d+)", pagenumbers)
        if page == 1:
            print "pages", pagenumbers
        assert mpagenumbers, pagenumbers
        assert int(mpagenumbers.group(1)) == page, (pagenumbers, int(mpagenumbers.group(1)), page)

        response = br.submit('ctl00$phMainContent$grantSearchResults$nextPage')
        root = lxml.html.fromstring(response.read())
        page += 1
    if ngrants != ngrantscount:
        print ("BAD DATE", datefrom, ngrants, ngrantscount)

def CreateViews():
    scraperwiki.sqlite.execute("DROP TABLE IF EXISTS quarter_conv")
    ldata = [ ]
    for year in range(1997, 2020):
        for month in range(0, 12):
            ldata.append({"isomonth":"%04d-%02d" % (year, month+1), "quarter":"%04dQ%d" % (year, month/3+1), 
                          "qmonth":"%04d-%02d" % (year, int(month/3)*3+3)})
    scraperwiki.sqlite.save(["isomonth"], ldata, "quarter_conv")

    scraperwiki.sqlite.execute("DROP VIEW IF EXISTS monthly_lottery_funding")
    scraperwiki.sqlite.execute('CREATE VIEW monthly_lottery_funding AS SELECT `Local authority`, strftime("%Y",`Grant date`) AS `Grant year`, strftime("%m",`Grant date`) AS `Grant month`, SUM(`Grant amount`) AS amount FROM swdata GROUP BY `Local authority`, strftime("%Y",`Grant date`), strftime("%m",`Grant date`)')
    scraperwiki.sqlite.execute("DROP VIEW IF EXISTS quarterly_lottery_funding")
    scraperwiki.sqlite.execute('CREATE VIEW quarterly_lottery_funding AS SELECT `Local authority`, `Grant year`, (`Grant month`+2)/3 AS `Grant quarter`, SUM(amount) AS amount FROM monthly_lottery_funding GROUP BY `Local authority`, `Grant year`, (`Grant month`+2)/3')

#Main()
CreateViews()
