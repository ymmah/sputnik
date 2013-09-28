var session = null;
var logged_in = false;

var QBUY, QSELL, PBUY, PSELL;
var MARKETS;
var SITE_TICKER = 'ERROR';
var TRADE_HISTORY = [];
var MAX_CHAT_LINES = 100;
var SITE_POSITIONS = [];
var OPEN_ORDERS = [];
var ORDER_BOOK; //Global variable will be useful when depth graph is built.

var ORDER_BOOK_VIEW_SIZE = false;

var CHAT_MESSAGES = [];
var SAFE_PRICES = Object();
var TWO_FACTOR_ON = false;

var base_uri = "http://example.com/";

var myTopic = base_uri + "topics/mytopic1";

var chat_URI = base_uri + "user/chat";
var fills_URI = base_uri + "user/fills#";
var cancels_URI = base_uri + "user/cancels#";
var open_orders_URI = base_uri + "user/open_orders#";
var trade_URI = base_uri + "trades#";
var safe_prices_URI = base_uri + "safe_prices#";
var order_book_URI = base_uri + "order_book#";

window.onload = function () {
    connect();
};

function onChat(channelURI, msg) {
    var user = msg[0];
    var message = msg[1];
    //CHAT_MESSAGES.push('&lt;' + user + '&gt; ' + message)
    // switched to colon to make uniformly formatted chats and chat history
    CHAT_MESSAGES.push(user +':' + message)
    if (CHAT_MESSAGES.length > MAX_CHAT_LINES)
        CHAT_MESSAGES.shift();


    $('#chatArea').html(CHAT_MESSAGES.join('\n'));
    //for(var i = 0; i < CHAT_MESSAGES.length; ++i)
    //    $('#chatArea').append(CHAT_MESSAGES[i]+'\n');

    $('#chatArea').scrollTop($('#chatArea')[0].scrollHeight);
}

function onSafePrice(uri, event) {
    var ticker = uri.split('#')[1];
    SAFE_PRICES[ticker] = event;
}

function onConnect() {
    console.log("Connected!")
    getMarkets();
    getChatHistory();
    session.subscribe(chat_URI, onChat);

}

function twoFactorSetting(){
    console.log(two_factor.value.length);
    console.log(two_factor.value.length > 0);

    if (two_factor.value.length > 0){
        TWO_FACTOR_ON = true;
    }

    if (TWO_FACTOR_ON) {
           $('#enableTwoFactor').removeClass('btn-success')
                               .addClass('btn-danger')
                               .text('Disable');
           $('#twoFactor').hide();
           $('#twoFactorInstructions').text('Enter your current otp number here disable two factor authentication:');
    } else {
           $('#enableTwoFactor').removeClass('btn-danger')
                               .addClass('btn-success')
                               .text('Enable');
           $('#twoFactor').show();
           $('#twoFactorInstructions').text('Enter the otp number here to enable two factor:');
    }

}

function onAuth(permissions) {
    ab.log("authenticated!", JSON.stringify(permissions));
    logged_in = true;


    $('#loggedInMenu').show();
    $('#dLabel').text('logged in as ' + login.value);

    $('#loginButton').hide();
    $('#registration').hide();
    
    //hacky fix of modal backdrop not being dismissed when authentication is preceded by failed login attempt
    $('.modal').modal('hide');

    // Initialize for user.  Maybe move the call for markets to before auth?
    //make this chain correctly...or better yet, make it publish upon connection
    //via serverside

    //getSafePrices(Object.keys(MARKETS));
    getSafePrices();
    getOpenOrders();
    getPositions();

    twoFactorSetting();

    /*
    the gleaning of the user_id from the permissions and then manual 
    subscription process is very hacky.  Hope to make it more clean later.
    */
    var user_id;
    user_id = _.pluck(permissions.pubsub, 'uri')[1].split('#')[1]
    console.log(cancels_URI + user_id );

    // switched user_id for login.value
    try{session.subscribe(cancels_URI + login.value, onCancel);}
        catch(err){console.log(err);}
    try{session.subscribe(fills_URI + login.value, onFill);}
        catch(err){console.log(err);}
    try{ session.subscribe(open_orders_URI + login.value, onOpenOrder);}
        catch(err){console.log(err);}

    switchBookSub (SITE_TICKER);
    //possible to subscribe to chat, but not pub before auth?
    session.subscribe(chat_URI, onChat);
}

function onEvent(topicUri, event) {
    console.log('in onEvent', SITE_TICKER, topicUri, event);

    if (SITE_TICKER in JSON.parse(event)) {
        console.log('got event');
        //todo: find where needed
        orderBook(SITE_TICKER);
        //getTradeHistory(SITE_TICKER);
    }
}

function onBookUpdate(topicUri, event) {
    console.log('in onBookUpdate');
	ORDER_BOOK = JSON.parse(event);
	updateOrderBook(ORDER_BOOK,ORDER_BOOK_VIEW_SIZE);
}

function onFill(topicUri, event) {
    //must get rid of safe price rpc!
    console.log('in onFill', SITE_TICKER, topicUri, event);

    getPositions(SITE_TICKER);
    getSafePrices(Object.keys(MARKETS));

    OPEN_ORDERS = _.reject(OPEN_ORDERS, function (ord) {return ord['order_id']== event['order'];});
    displayPositions(false,SITE_POSITIONS);
    displayPositions(true,SITE_POSITIONS);
    displayOrders(false,OPEN_ORDERS);
    displayOrders(true,OPEN_ORDERS);
    //reload position tableS
    //make some sort of notification to user
}

function onOpenOrder(topicUri, event) {
    //must get rid of safe price rpc!
    console.log('in onOpenOrder', SITE_TICKER, topicUri, event);

    getSafePrices(Object.keys(MARKETS));


    var new_open_order = {'order_id': event['order'],
                          'price':    event['price'],
                          'quantity': event['quantity'],
                          'side':     event['side']==0?'BUY':'SELL',
                          'ticker':   event['ticker']};
    OPEN_ORDERS.push(new_open_order);
    
//    displayPositions(false,SITE_POSITIONS);
//    displayPositions(true,SITE_POSITIONS);
//      replace with 
    getPositions();
    displayOrders(false,OPEN_ORDERS);
    displayOrders(true,OPEN_ORDERS);
}

function onCancel(topicUri, event) {
    console.log('in onCancel', SITE_TICKER, topicUri, event);

    OPEN_ORDERS = _.reject(OPEN_ORDERS, function (ord) {return ord['order_id']== event['order'];});

    displayPositions(false,SITE_POSITIONS);
    displayPositions(true,SITE_POSITIONS);
    OPEN_ORDERS = _.reject(OPEN_ORDERS, function (ord) {return ord['order_id']== event['order'];});
    displayOrders(false,OPEN_ORDERS);
    displayOrders(true,OPEN_ORDERS);
    //reload position tableS
    //make some sort of notification to user
}

function onTrade(topicUri, event) {
    //must get rid of safe price rpc!
    console.log('in onTrade', SITE_TICKER, topicUri, event);

    getSafePrices(Object.keys(MARKETS));

	now = new Date().toLocaleTimeString();
	updateTradeTable([now, event['price'], event['quantity'] ]);
}

//subscribe functions (may want to put intial rpc call in them as well)

function subToTradeStream(ticker) {   
	console.log(trade_URI+ticker ,onTrade);
	session.subscribe(trade_URI+ticker ,onTrade);
}

function subToSafePrice(ticker) {   
	console.log(safe_prices_URI+ticker ,onSafePrice);
	session.subscribe(safe_prices_URI+ticker ,onSafePrice);
}

function subToOrderBook(ticker) {   
	console.log(order_book_URI+ticker, onBookUpdate);
	session.subscribe(order_book_URI+ticker, onBookUpdate);
}

function subToOpenOrders(id) {   
	console.log(open_orders_URI + id, onOpenOrder);
	session.subscribe(open_orders_URI + id, onOpenOrder);
}

function subToFills(id) {   
	console.log(fills_URI + id, onFill);
	session.subscribe(fills_URI + id, onFill);
}

function subToCancels(id) {   
	console.log(cancels_URI + id, onCancel);
	session.subscribe(cancels_URI + id, onCancel);
}

function sendChat(message) {
    session.publish(chat_URI, message, false)
}

function setSiteTicker(ticker) {
    SITE_TICKER = ticker;
    $('.contract_unit').text(MARKETS[SITE_TICKER]['contract_type'] == 'futures' ? '฿' : '%');
}

//currency functions

function deposit() {
    getCurrentAddress();
    $('#depositModal').modal('show');
}

function withdrawModal() {
    $('#withdrawModal').modal('show');
}

function calculateMargin(positions, open_orders, safe_prices) {
    var low_margin = 0;
    var high_margin = 0;
    var margins = {};

    for (var key in positions) {
        var position = positions[key];

        if (position.contract_type == 'cash')
            continue;

        /*todo:temporary hack, resolve this more cleanly...
         what happens if we have positions in an inactive market?
         */
        if (!(position.ticker in MARKETS))
            continue;

        var max_position = position.position;
        var min_position = position.position;
        for (var j = 0; j < open_orders.length; ++j) {
            var order = open_orders[j];
            if (order.ticker == position.ticker) {
                if (order.side == 'BUY')
                    max_position += order.quantity;
                if (order.side == 'SELL')
                    min_position -= order.quantity;
            }
        }

        if (MARKETS[position.ticker].contract_type == 'futures') {
            var safe_price = safe_prices[position.ticker];
            var low_max = Math.abs(max_position) * MARKETS[position.ticker].margin_low * safe_price / 100 +
                max_position * (position.reference_price - safe_price);
            var low_min = Math.abs(min_position) * MARKETS[position.ticker].margin_low * safe_price / 100 +
                min_position * (position.reference_price - safe_price);
            var high_max = Math.abs(max_position) * MARKETS[position.ticker].margin_high * safe_price / 100 +
                max_position * (position.reference_price - safe_price);
            var high_min = Math.abs(min_position) * MARKETS[position.ticker].margin_high * safe_price / 100 +
                min_position * (position.reference_price - safe_price);

            high_margin += Math.max(high_max, high_min);
            low_margin += Math.max(low_max, low_min);
            margins[position.ticker] = [Math.max(high_max, high_min), Math.max(low_max, low_min)];
        }
        if (MARKETS[position.ticker].contract_type == 'prediction') {

            var payoff = MARKETS[position.ticker].final_payoff;
            var max_spent = 0;
            var max_received = 0;

            for (var j = 0; j < open_orders.length; ++j) {
                var order = open_orders[j];
                if (order.ticker == position.ticker) {
                    if (order.side == 'BUY')
                        max_spent += order.quantity * order.price;
                    if (order.side == 'SELL')
                        max_received += order.quantity * order.price;
                }
            }

            var worst_short_cover = Math.max(-min_position, 0) * payoff;
            var best_short_cover = Math.max(-max_position, 0) * payoff;

            var additional_margin = Math.max(max_spent + best_short_cover, -max_received + worst_short_cover);
            low_margin += additional_margin;
            high_margin += additional_margin;
            margins[position.ticker] = [additional_margin, additional_margin];
        }
    }
    margins['total'] = [low_margin, high_margin];
    return margins;
    //return [low_margin, high_margin];
}

//charting functions:
function decimalPlacesNeeded(denominator) {
    var factor_five = 0;
    var factor_two = 0;
    while (denominator % 5 == 0) {
        ++factor_five;
        denominator /= 5;
    }
    while (denominator % 2 == 0) {
        ++factor_two;
        denominator /= 2;
    }
    return Math.max(factor_five, factor_two);
}

function stackBook(book) {
    var newBook = [];

    book.sort(function (a, b) {
        return parseFloat(a[0]) - parseFloat(b[0])
    });

    if (book.length == 0)
        return [];

    var price = book[0][0];
    var quantity = book[0][1];

    for (var i = 1; i < book.length; i++) {
        if (book[i][0] == price) {
            quantity += book[i][1];
        } else {
            newBook.push([quantity, price]);
            price = book[i][0];
            quantity = book[i][1];
        }
    }
    newBook.push([quantity, price]);

    return newBook;
}

function build_trade_graph(trades) {
    var parseDate = d3.time.format("%Y-%m-%dT%H:%M:%S").parse;
    var data = [];

    // first, prepare the data to be in the cross-filter format
    for (var i = 0; i < trades.length; ++i) {
        data.push(
            {
                'date': parseDate(trades[i][0].split('.')[0]),
                'price': trades[i][1] / MARKETS[SITE_TICKER]['denominator'],
                'quantity': trades[i][2]
            });
    }
    var cd = crossfilter(data);
    var time_dimension = cd.dimension(function (d) {
        return d.date;
    });
    var volume_group = time_dimension.group().reduceSum(function (d) {
        return d.quantity;
    });
    var volume_weighted_price = time_dimension.group().reduce(
        // add
        function (p, v) {
            p.total_volume += v.quantity;
            p.price_volume_sum_product += v.price * v.quantity;
            p.volume_weighted_price = p.price_volume_sum_product / p.total_volume;
            return p;
        },
        // remove
        function (p, v) {
            p.total_volume -= v.quantity;
            p.price_volume_sum_product -= v.price * v.quantity;
            p.volume_weighted_price = p.price_volume_sum_product / p.total_volume;
            return p;
        },
        // init
        function () {
            return {'total_volume': 0, 'price_volume_sum_product': 0, 'volume_weighted_price': NaN}
        }
    );

    var priceChart = dc.compositeChart("#monthly-move-chart");
    var volumeChart = dc.barChart("#monthly-volume-chart");

    var numberFormat = d3.format(".2f");
    var dateFormat = d3.time.format("%Y-%M-%dT%H:%M:%S");

    priceChart.width(700)
        .height(180)
        .transitionDuration(1000)
        .margins({top: 10, right: 50, bottom: 25, left: 40})
        .dimension(time_dimension)
        .group(volume_weighted_price)
        .valueAccessor(function (d) {
            return d.value.volume_weighted_price;
        })
        .mouseZoomable(true)
        .x(d3.time.scale().domain([data[0]['date'], data[data.length - 1]['date']]))
        .round(d3.time.minutes.round)
        .xUnits(d3.time.minutes)
        .elasticY(true)
        .yAxisPadding("20%")
        .renderHorizontalGridLines(true)
        .brushOn(false)
        .rangeChart(volumeChart)
        .compose([
            dc.lineChart(priceChart).group(volume_weighted_price)
                .valueAccessor(function (d) {
                    return d.value.volume_weighted_price;
                })
                .renderArea(true)
        ])
        .xAxis();

    volumeChart.width(700)
        .height(50)
        .margins({top: 0, right: 50, bottom: 20, left: 40})
        .dimension(time_dimension)
        .group(volume_group)
        .centerBar(true)
        .gap(1)
        .x(d3.time.scale().domain([data[0]['date'], data[data.length - 1]['date']]))
        .round(d3.time.minute.round)
        .xUnits(d3.time.minutes);

    dc.renderAll();

}

function displayPrice(price, denominator, tick_size, contract_type) {
    var contract_unit = '฿';
    var percentage_adjustment = 1;
    if (contract_type == 'prediction') {
        contract_unit = '%';
        percentage_adjustment = 100;
    }
    var dp = decimalPlacesNeeded(denominator / ( percentage_adjustment * tick_size));

    return ((price * percentage_adjustment) / denominator).toFixed(dp) + ' ' + contract_unit;

}

function updateOrderBook(book, full_size) {
    console.log('in updateOrderBook');
	for (key in book){
			book = book[key];	
            var buyBook = [];
            var sellBook = [];

            var denominator = MARKETS[key]['denominator'];
            var tick_size = MARKETS[key]['tick_size'];
            var contract_type = MARKETS[key]['contract_type'];

            for (var i = 0; i < book.length; i++) {
                var price = Number(book[i]['price']);
                var quantity = book[i]['quantity'];
                ((book[i]['order_side'] == 0) ? buyBook : sellBook).push([price , quantity]);
            }

            buyBook = stackBook(buyBook);
            sellBook = stackBook(sellBook);

            sellBook.reverse();

            graphTable(buyBook, "buy",true);// ORDER_BOOK_VIEW_SIZE);
            graphTable(sellBook, "sell",true);//ORDER_BOOK_VIEW_SIZE);
	}
}

function updateTradeTable(trade) {
    console.log('recieved trade');
    console.log(trade);
	var direction = '';

	if (trade[1] > TRADE_HISTORY[0][1]) {
		direction = 'success';
	} else if (trade[1] < TRADE_HISTORY[0][1]) {
		direction = 'error';
	} /*else {
		direction = 'neutral';
	}*/


	$('#tradeHistory tr:first').after("<tr class=" + direction + ">" +
		"<td>" + displayPrice(trade[1], MARKETS[SITE_TICKER]['denominator'], MARKETS[SITE_TICKER]['tick_size'], MARKETS[SITE_TICKER]['contract_type']) + "</td>" + // don't show ticker unless needed
		"<td>" + trade[2] + "</td>" +
		"<td>" + trade[0] + "</td>" +
		"</tr>");

	TRADE_HISTORY.push(trade);  //vs. unshift() ...?
}

function tradeTable(trades, fullsize) {
    console.log('in tradeTable');

    var length = fullsize ? trades.length : 25;
    $('#tradeHistory').empty()

    var direction = 'neutral';
    if (!fullsize) {trades = trades.slice(0,25)};

    trades.reverse();   /*trades.reverse is called again after the for loop.
                         trying to get the order right.*/

    for (var i = 1; i < trades.length; i++) {
        if (trades[i][1] > trades[i - 1][1]) {
            direction = 'success';
        } else if (trades[i][1] < trades[i - 1][1]) {
            direction = 'error';
        } 

        $('#tradeHistory').prepend("<tr class=" + direction + ">" +
            "<td>" + displayPrice(trades[i][1], MARKETS[SITE_TICKER]['denominator'], MARKETS[SITE_TICKER]['tick_size'], MARKETS[SITE_TICKER]['contract_type']) + "</td>" + // don't show ticker unless needed
            "<td>" + trades[i][2] + "</td>" +
            "<td>" + new Date(trades[i][0]).toLocaleTimeString() + "</td>" +
            "</tr>");
    }
    trades.reverse();


    $('#tradeHistory').prepend('<tr><th>Price <p class=\'contract_unit\'></p> </th><th>Vol.</th><th>Time</th></tr>');

    //Removing table size variance buttons
    /*
    $('#tradeHistory').append(
        fullsize ?
            '<tr><td colspan="3"><button id="lessTrades" class="btn btn-block"><i class="icon-chevron-up"/></button></td></tr>' :
            '<tr><td colspan="3"><button id="moreTrades" class="btn btn-block"><i class="icon-chevron-down"/></button></td></tr>'
    );
    */

    $('#lessTrades').click(function () {
        tradeTable(TRADE_HISTORY, false);
    });

    $('#moreTrades').click(function () {
        tradeTable(TRADE_HISTORY, true);
    });
}

function suggestOrder() {
        $('#psell').val(PSELL);
        $('#qsell').val(QSELL);
        $('#pbuy').val(PBUY);
        $('#qbuy').val(QBUY);
};

function graphTable(table, side, fullsize) {
    console.log('in graphTable');
    console.log(fullsize);
    var length = fullsize ? table.length : 10;
    var id = (side == 'buy') ? '#orderBookBuys' : '#orderBookSells';

	var denominator = MARKETS[SITE_TICKER]['denominator'];
	var contract_type = MARKETS[SITE_TICKER]['contract_type'];
	var tick_size = MARKETS[SITE_TICKER]['tick_size'];

    $(id).empty();
	
    // update the suggested buy/sell orders:
    if (table.length >0) {
        if (side =='buy') {
            PSELL = displayPrice(table[table.length - 1][1], denominator, tick_size, contract_type).split(' ')[0];
            QSELL = table[table.length - 1][0];
        } else {
            PBUY = displayPrice(table[table.length - 1][1], denominator, tick_size, contract_type).split(' ')[0];
            QBUY = table[table.length - 1][0];
        }
    }

    for (var i = 0; i < Math.max(10,length); i++) {
        if (i < table.length) {
            //ugly reversing of table.. meh, it's working..
            var j = table.length - i -1;
            var price_cell = "<td>" + displayPrice(table[j][1], denominator, tick_size, contract_type) + "</td>";
            var quantity_cell = "<td>" + table[j][0] + "</td>";
            var row_string = (side == 'buy' ? quantity_cell + price_cell : price_cell + quantity_cell);
            $(id).append("<tr id='" + side + "_" + i + "'>" + 
							row_string + "</tr>");

			// highlight user's orders
			if (_.contains(
                            _.pluck(
                                    _.filter(OPEN_ORDERS, function (order){return order['ticker']==SITE_TICKER;})
                                    ,'price')
                            ,table[j][1] )
               ) {
				$('#' + side + '_' + i).addClass("info");
			}
        }
        else {
            $(id).append("<tr><td> - </td><td> - </td></tr>");
        }
    }

    // add headers

    var price_header = "<th>" + (side == 'buy' ? "Bid" : "Ask") + "<p class='contract_unit'></p> </th>";
    var volume_header = "<th>Volume</th>";

    $(id).prepend("<tr>" + (side == 'buy' ? volume_header + price_header : price_header + volume_header) + "</tr>");

    //removing size variability
    /*
    $(id).append(
        fullsize ?
            '<tr><td colspan="2"><button  class="lessOrderBook btn btn-block"><i class="icon-chevron-up"/></button></td></tr>' :
            '<tr><td colspan="2"><button  class="moreOrderBook btn btn-block"><i class="icon-chevron-down"/></button></td></tr>'
    );
    */

    $('.lessOrderBook').click(function () {
        console.log('less');
        ORDER_BOOK_VIEW_SIZE = false;
        updateOrderBook(ORDER_BOOK,ORDER_BOOK_VIEW_SIZE);
    });

    $('.moreOrderBook').click(function () {
        console.log('more');
        ORDER_BOOK_VIEW_SIZE = true;
        updateOrderBook(ORDER_BOOK,ORDER_BOOK_VIEW_SIZE);
    });
}

function displayOrders(show_all_tickers, orders) {
    var element = show_all_tickers ? '#openOrders' : '#market_order_table';
//    var margins = calculateMargin(SITE_POSITIONS, OPEN_ORDERS, SAFE_PRICES);
    $(element).empty()
        .append("<thead><tr>" +
            (show_all_tickers ? "<th>Ticker</th>" : "") +
            "<th>"+ (show_all_tickers?"Quantity":"#") +"</th>" +
            "<th>Price</th>" +
            "<th>Buy/Sell</th>" +
            "<th>Cancel</th>" +
//            "<th>Reserved</th>" +
            "</tr></thead><tbody>");

    _.each(_.groupBy(OPEN_ORDERS, function (orders) {return orders['ticker'];}),
        function (contract_group, ticker) {
            var length = _.size(contract_group);

            if (show_all_tickers || ticker == SITE_TICKER) { // if this SITE_TICKER is to be shown

                var ticker_td = (show_all_tickers ? "<td rowspan='" + length + "' style='vertical-align:middle' class='ordersDisplay'  id='"+ ticker +"'>" + ticker  + "</td>" : "") // don't show ticker unless needed
//                var margin_td = (show_all_tickers ? "<td rowspan='" + length + "'>" + margins[ticker][1] / 1e8 + "</td>" : "") // don't show ticker unless needed
                var printed_ticker;
                _.each(contract_group, function (order) {
                    var quantity = order['quantity'];
                    var price = displayPrice(
                        order['price'],
                        MARKETS[order['ticker']]['denominator'],
                        MARKETS[order['ticker']]['tick_size'],
                        MARKETS[order['ticker']]['contract_type']);
                       
                    $(element).append("<tr id='cancel_order_row_" + order['order_id'] + "'>" +

                        (printed_ticker?'':ticker_td) +
                        "<td>" + quantity + "</td>" +
                        "<td nowrap>" + price + "</td>" +
                        "<td>" + order['side'] + "</td>" +
                        "<td>" +
                        "<button id='cancel_button_" + order['order_id'] + "' class='cancelButtons btn btn-block btn-danger' type='button' >" + (show_all_tickers?'cancel':'') + "<i class='icon-trash'/></button>" +
                        "</td>" +
                        "</tr>");
                    printed_ticker = true;
                });
            }
        $(element).append("</thead>");
       });

       $('.cancelButtons').unbind()
                          .click(function(e){
                                cancelOrder(parseInt((e.currentTarget.id).split('_')[2]));
                           });

       $('.ordersDisplay').unbind('click')
                          .click(function (e){
                                switchToTrade(e.currentTarget.id);
                          });
}

function displayCash(display_account_page, positions) {
    var element = display_account_page ? '#account_cash_table' : '#cash_table';
    var margins = calculateMargin(SITE_POSITIONS, OPEN_ORDERS, SAFE_PRICES);
    $(element).empty()
        .append("<tr>" +
            "<th>Currency</th>" +
            "<th>Position</th>" +
            //"<th>Low Margin</th>" +
            "<th>Reserved in Margin</th>" +
            (display_account_page ?  "<th>Withdraw</th><th>Deposit</th>":"")
            + "</tr>");

    for (var key in positions) {
        $(element).append("<tr>" +
            "<td>" + positions[key]['ticker'] + "</td>" + 
            "<td>" + (positions[key]['position'] / 1e8) + "</td>" +
            //"<td>" + margins['total'][0] / 1e8 + "</td>" +
            "<td>" + margins['total'][1] / 1e8 + "</td>" +
            
            (display_account_page?
            "<td>" +
            "<button id='withdrawModalButton'  class='btn btn-block' type='button'>" +
            " <i class='icon-minus-sign'/>" +
            "</button>" +
            "</td>" +
            "<td>" +
            "<button id='depositButton' class='btn btn-block' type='button'>" +
            " <i class='icon-plus-sign'/>" +
            "</button>" +
            "</td>" 
            : "")


            + "</tr>");
    }

    $('#depositButton').click(function(){
        deposit()
    });

    $('#withdrawModalButton').click(function(){
        withdrawModal()
    });
}

function displayPositions(show_all_tickers, positions) {
    var element = show_all_tickers ? '#account_positions_table' : '#market_position_table';
    var margins = calculateMargin(SITE_POSITIONS, OPEN_ORDERS, SAFE_PRICES);
    $(element).empty()
        .append("<thead><tr>" +
            (show_all_tickers ? "<th>Ticker</th>" : "") +
            "<th>Position</th>" +
            "<th>Reference Price</th>" +
			//<th>Low Margin</th>
			"<th>Reserved for Margin</th></tr></thead><tbody>");

    // remove cash and old inactive positions
    positions = _.reject(positions, function (contract) {return contract['contract_type'] =='cash';});
    // using the underscore library function _.indexOf() as IE doesn't support the standard Array.indexOf().  Haven't actually checked - Just hoping.
    positions = _.filter(positions, function (contract) {return _.indexOf(Object.keys(margins), contract['ticker'])>-1;});

    for (var key in positions) {
        if (show_all_tickers || (positions[key]['ticker'] == SITE_TICKER)) {// if this ticker is to be shown
            var ticker = positions[key]['ticker'];//(typeof positions[key]['ticker'] =='number')?SITE_POSITIONS[ticker]['ticker']:positions[key]['ticker']
            $(element).append("<tr>" +
                (show_all_tickers ? "<td class='positionDisplays' id='"+ ticker +"' >" + ticker + "</td>" : "") + // don't show ticker unless needed
                "<td>" + positions[key]['position'] + "</td>" +
                "<td>" + (positions[key]['reference_price'] / 1e8) + "</td>" +
                //"<td>" + margins[ticker][1] / 1e8 + "</td>" +
                "<td>" + margins[ticker][0] / 1e8 + "</td>" +
                "</tr>");
            }
    }
    $(element).append("</tbody>");

    $('.positionDisplays').unbind();
    $('.positionDisplays').click(function(e) {
        switchToTrade(e.currentTarget.id);
    });
}


function newMarketsToDisplay(markets) {

    markets = _.pairs(markets);    

    var predictions = _.filter(markets, function(item) { return item[1]["contract_type"] == "prediction";});
    var futures = _.filter(markets, function(item) { return item[1]["contract_type"] == "futures";});
    
    var pList = [];
    for (market in predictions){
        pList.push("<li><a class='newMarkets' id='" + predictions[market][0] + "' href='#'> <small style='padding-right:1em;'>" +  predictions[market][0] + "</small>"+predictions[market][1]['description'] + "</a></li>")
    }

    var fList = [];
    for (market in futures){
        fList.push("<li><a class='newMarkets' id='" + futures[market][0] + "' href='#'><small style='padding-right:1em;'>" +  futures[market][0] + "</small>"+futures[market][1]['description'] + "</a></li>")
    }

    $('#marketsDropDown').html( '<li class="nav-header">Predictions</li>' + pList.join('') + '<li class="nav-header">Futures</li>' + fList.join('') );

    $('.newMarkets').unbind();
    $('.newMarkets').click(function(e) {
        switchToTrade(e.currentTarget.id);
    });
}

/*
function marketsToDisplayTree(markets) {
    var displayMarket = {};
    displayMarket['key'] = 'Markets';
    displayMarket['values'] = [];

    var futures = {};
    var predictions = {};
    var myMarkets = {};

    futures['key'] = 'Futures';
    predictions['key'] = 'Predictions';
    myMarkets['key'] = 'My Markets';

    futures['values'] = [];
    predictions['values'] = [];
    myMarkets['values'] = [];


    for (key in markets) {
        var entry = {
            'key': markets[key]['description'],
            'ticker': key,
            'action': key
        };
        (markets[key]['contract_type'] == 'futures' ? futures : predictions)['values'].push(entry);

        if (true)           // todo: check for markets the user has positions on.
            myMarkets['values'].push(entry)
    }

    displayMarket['values'].push(futures);
    displayMarket['values'].push(predictions);
    displayMarket['values'].push(myMarkets);

    return [displayMarket];
}
*/

function welcome (MARKETS) {
    var markets = MARKETS;
    $('#welcome').empty()
        $('#welcome').append("<thead><tr>" +
            "<th>Most Active Markets</th>" +
            "<th>Description</th>" +
            "</tr></thead>");

    for (row in markets) {
        $('#welcome').append("<tr class='splash' id='"+ row +"' >" +
            "<td>"+ row + "</td>" +
            "<td>" + markets[row]['description'] + "</td>" +
            "</tr>");

    }

    $('.splash').unbind();
    $('.splash').click(function(e) {
        switchToTrade(e.target.parentNode.id);
    });

    var scalingFactor = $(window).height()/$(window).width();
    $('#splash').css('z-index','-1')
                .css('width',parseInt(100*scalingFactor*0.55) + '%')
                .css('position','absolute')
                .css('top', '15%')
                .css('right', '5%')
                .show();
}

/*
function tree(datafunction) {
    nv.addGraph(function () {
        var chart = nv.models.indentedTree()
            .tableClass('table table-striped') //for bootstrap styling
            .columns([
                {
                    key: 'key',
                    label: 'Name',
                    showCount: true,
                    width: '75%',
                    type: 'text'
                },
                {
                    key: 'ticker',
                    label: 'Ticker',
                    width: '25%',
                    type: 'text',
                    classes: function (d) {
                        return d.action ? 'clickable name' : 'name';
                    },
                    click: function (d) {
                        if (d.action) {
                            switchToTrade(d.action);
                            //setSiteTicker(d.action);
                            //$('#Trade').click();
                        }
                    }
                }
            ]);
        d3.select('#tree')
            .datum(datafunction)
            .call(chart);
        return chart;
    });
}
*/


function switchToTrade (new_ticker) {
    console.log('in switchToTrade');
    switchBookSub(new_ticker);
	$('#Trade').click();
}

function switchBookSub (ticker) {
    //need to fix this hardcoding
    id = SITE_TICKER=='USD.13.7.31'?17:16; 

    if (logged_in) {
        try{session.unsubscribe(order_book_URI+SITE_TICKER, onBookUpdate);}
            catch(err){console.log(err);}
        try{session.unsubscribe(trade_URI+SITE_TICKER,onTrade);}
            catch(err){console.log(err);}
        try{ session.unsubscribe(safe_prices_URI+SITE_TICKER ,onSafePrice);}
            catch(err){console.log(err);}
    }

    /*
    try{session.unsubscribe(cancels_URI + user_id, onCancel);}
        catch(err){console.log(err);}
    try{session.unsubscribe(fills_URI + user_id, onFill);}
        catch(err){console.log(err);}
    try{ session.unsubscribe(open_orders_URI + user_id, onOpenOrder);}
        catch(err){console.log(err);}
    */

	setSiteTicker(ticker);

    id = SITE_TICKER=='USD.13.7.31'?17:16; 

	try{session.subscribe(order_book_URI+SITE_TICKER, onBookUpdate);}
        catch(err){console.log(err);}
	try{session.subscribe(trade_URI+SITE_TICKER,onTrade);}
        catch(err){console.log(err);}
    try{ session.subscribe(safe_prices_URI+SITE_TICKER ,onSafePrice);}
        catch(err){console.log(err);}

}

//Notification messages
var notifications = new Object();

notifications.orderError = function () {
    alert('Order error: must be between 0.0% and 100.0%');
};
notifications.processing = function (msg) {
    $('#processingModal').modal('show');
};
notifications.dismiss_processing = function (msg) {
    $('.modal').modal('hide');
    //$('#processingModal').modal('hide');
};


$('#Trade').click(function () {
    $('#currentMarket').html(MARKETS[SITE_TICKER]['description']);
    $('#currentTicker').html(SITE_TICKER);
    $('#descriptionText').html(MARKETS[SITE_TICKER]['full_description']);

    getTradeHistory(SITE_TICKER);
    orderBook(SITE_TICKER);

    if (logged_in) {
        getOpenOrders();
        getPositions();
    }
    //suggestOrder();

});

$('#Account').click(function () {
    getPositions();
    getOpenOrders();
    if (!logged_in) {
        $('#loginButton').click()
    }
});

$('#logoutButton').click(function () {

    $('#loggedInMenu').hide();
    $('#dLabel').text('');

    logout();

    $('#loginButton').show();
    $('#registration').show()
});

$('#registerButton').click(function () {
    makeAccount(registerLogin.value, registerPassword.value, registerEmail.value, registerBitMessage.value);
});


function orderButton(q, p, s) {
    if (!logged_in) {
        $('#loginButton').click()
    } else {
        var ord = {};
        var price_entered = Number(p);
        ord['ticker'] = SITE_TICKER;
        ord['quantity'] = parseInt(q);
        var tick_size = MARKETS[SITE_TICKER]['tick_size'];
        var percentage_adjustment = (MARKETS[SITE_TICKER]['contract_type'] == 'prediction' ? 100 : 1);
        ord['price'] = Math.round((MARKETS[SITE_TICKER]['denominator'] * price_entered) / (percentage_adjustment * tick_size)) * tick_size;
        ord['side'] = s;
        placeOrder(ord);
    }
}

function checkOrder(side) {
    var price    = (side == 'buy' ? pbuy.value : psell.value);
    var quantity = (side == 'buy' ? qbuy.value : qsell.value);

    if (quantity.length ==0 ) {
        $('.modal').modal('hide');
       //$('#processingModal').modal('hide');
       alert('Quantity must be non-zero');
       return false;
    } else if (isNaN(quantity) || isNaN(price) ){
        $('.modal').modal('hide');
       //$('#processingModal').modal('hide');
       alert('Please only enter numbers');
       return false;
    } else if (parseFloat(price) * 1e8 %MARKETS[SITE_TICKER]['tick_size'] > 0){
       $('.modal').modal('hide');
       //$('#processingModal').modal('hide');
       alert('The tick size of this contract is: 1/'+ 1e8 /MARKETS[SITE_TICKER]['tick_size'] );
       return false;
    } else {
        return true;
    }
}


$('#sellButton').click(function () {
    if (checkOrder('sell')){
        orderButton(qsell.value, psell.value, 1);
    }
});

$('#buyButton').click(function () {
    if (checkOrder('buy')){
        orderButton(qbuy.value, pbuy.value, 0);
    }
});

$('#chatButton').click(function () {
    sendChat(chatBox.value);
    $('#chatBox').val('');
});

$('#newAddressButton').click(function () {
    getNewAddress();
    getCurrentAddress();
});

$('#chatFooterButton').click(function () {
    $('.footer').collapse('toggle');
    $('input#chatBox.chatInput').focus();
    $('#chatFooterButton').hide();
});

$('#minimizeChat').click(function () {
    $('#chatFooterButton').show();
    $('.footer').collapse('toggle');
});

$('.global-modal').on('hidden', function() {
    //the global-modal class consists of: 'myModal' (login) and 'registerModal'
    if (!logged_in)
        $('#Sputnik').click();

})

$('#Sputnik').click(function () {
    //remove the outline of a tab
    $('li.active').removeAttr('class','active');
    welcome (MARKETS)
});

$("#searchButton").click(function () {
    if (search.value =='BTC.13.7.12.gt.70'){
        $('#USD').hide();
        $('#searchPlaceHolder').hide()
        $('#BTC').show();
    } else if (search.value =='USD.13.7.31'){
        $('#BTC').hide();
        $('#searchPlaceHolder').hide()
        $('#USD').show();
    } else {
        $('#BTC').hide();
        $('#USD').hide();
        $('#searchPlaceHolder').show()
    }
})

$('#enableTwoFactor').click(function () {
    if (!TWO_FACTOR_ON) {
        getNewTwoFactor();
    }  
    $('#registerTwoFactor').prop('value','');
    $('#twoFactorModal').modal('show');
});

$('#changePassword').click(function () {
    $('#changePasswordModal').modal('show');
});

$('#submitPasswordChange').click(function () {
    console.log('button clicked');
    if (new_password.value == new_password_confirm.value){
        change_password(old_password.value, new_password.value);
    } else {
        alert("new password doesn't match confirmation");
    }
});

$('#submitTwoFactor').click(function(){
    if(!TWO_FACTOR_ON){
        registerTwoFactor( parseInt($('#registerTwoFactor').val()));
    } else {
       disableTwoFactor( parseInt($('#registerTwoFactor').val())); 
    }
});

$('#suggestContractButton').click(function () {
    $('#suggestionModal').modal('show');
});

$("input#search").keypress(function (e) {
    var code = (e.keyCode ? e.keyCode : e.which);
    if (code == 13) {
        $('#searchButton').click();
    }
});

$('#registerTwoFactor').keypress(function (e) {
    var code = (e.keyCode ? e.keyCode : e.which);
    if (code == 13) {
        $('#submitTwoFactor').click();
    }
});


$("input#chatBox.chatInput").keypress(function (e) {
    var code = (e.keyCode ? e.keyCode : e.which);
    if (code == 13) {
        $('#chatButton').click();
    }
});

//modals

$('#myModal').on('shown', function () {
    $('#login').focus();
});

$('#registerModal').on('shown', function () {
    $('#registerLogin').focus();
});

//keypress
$("#login").keypress(function (e) {
    var code = (e.keyCode ? e.keyCode : e.which);
    if (code == 13) {
        $('#do_login_button').click();
    }
});

$("#password").keypress(function (e) {
    var code = (e.keyCode ? e.keyCode : e.which);
    if (code == 13) {
        $('#do_login_button').click();
    }
});

$("#two_factor").keypress(function (e) {
    var code = (e.keyCode ? e.keyCode : e.which);
    if (code == 13) {
        $('#do_login_button').click();
    }
});

/*
$(window).resize(
    if ( $(window).width() < 1111) {
        $('#leftControlPanel').hide()
    } else {
        $('#leftControlPanel').show()
    }
})
*/

//$(window).load(controlPanelDisplay);
//$(window).resize(controlPanelDisplay);
$(window).resize(welcome(MARKETS));
//$(window).resize(tradeLayout());


// onload

var session = null;


var base_uri = "http://example.com/";
var get_chat_history_URI = base_uri + "procedures/get_chat_history";

var safe_price_URI = base_uri + "safe_price";
var get_safe_prices_URI = base_uri + "procedures/get_safe_prices";
var place_order_URI = base_uri + "procedures/place_order";
var get_trade_history_URI = base_uri + "procedures/get_trade_history";
var markets_URI = base_uri + "procedures/list_markets";
var positions_URI = base_uri + "procedures/get_positions";
var get_order_book_URI = base_uri + "procedures/get_order_book";
var make_account_URI = base_uri + "procedures/make_account";
var get_open_orders_URI = base_uri + "procedures/get_open_orders";
var cancel_order_URI = base_uri + "procedures/cancel_order";

var register_two_factor_URI= base_uri + "procedures/register_two_factor";
var get_new_two_factor_URI= base_uri + "procedures/get_new_two_factor";
var disable_two_factor_URI= base_uri + "procedures/disable_two_factor";

var change_password_URI = base_uri + "procedures/change_password";
var get_new_address_URI = base_uri + "procedures/get_new_address";
var get_current_address_URI = base_uri + "procedures/get_current_address";
var withdraw_URI = base_uri + "procedures/withdraw";

var AUTHEXTRA = {"keylen": 32, "salt": "RANDOM SALT", "iterations": 1000};



// connect to Autobahn.ws
function connect() {
    //ws -> wss
    var wsuri;// = "wss://" + host + ":9000";
    if (window.location.protocol === "file:") {
        //wsuri = "wss://localhost:9000";
        wsuri = "ws://localhost:9000";
    } else {
        //wsuri = "wss://" + window.location.hostname + ":9000";
        wsuri = "ws://" + window.location.hostname + ":9000";
    }
    ab.connect(wsuri,
        function (sess) {
            session = sess;
            ab.log("connected to " + wsuri);
            onConnect();
        },

        function (code, reason, detail) {
            //alert('disconnected!!!');
            $('#loggedOut').modal('show');
            logout();
            session = null;
            switch (code) {
                case ab.CONNECTION_UNSUPPORTED:
                    window.location = "http://autobahn.ws/unsupportedbrowser";
                    break;
                case ab.CONNECTION_CLOSED:
                    window.location.reload();
                    break;
                default:
                    ab.log(code, reason, detail);
                    break;
            }
        },

        {'maxRetries': 1, 'retryDelay': 1000}
    );
}

function do_login(login, password) {
    session.authreq(login /*, extra*/).then(function (challenge) {
        AUTHEXTRA = JSON.parse(challenge).authextra
        console.log('challenge', JSON.parse(challenge).authextra);
        console.log( ab.deriveKey(password, JSON.parse(challenge).authextra));
        console.log(two_factor.value);

        var secret = two_factor.value + ab.deriveKey(password, JSON.parse(challenge).authextra);

        //hash again to interpolate two_factor:
        secret = ab.deriveKey(secret, {'iterations':10, 'keylen':32, 'salt':'onetimepass'})

        //var secret = ab.deriveKey(password, JSON.parse(challenge).authextra);

        console.log(challenge);
        console.log( session.authsign(challenge, secret) );
        var signature = session.authsign(challenge, secret);
        console.log(signature)

        session.auth(signature).then(onAuth, failed_login);//ab.log);
        console.log('end of do_login');
    }, function (err) {
        failed_login('bad login');
    });
}

$('#do_login_button').click(function(){
    do_login(login.value, password.value);
});

function failed_login(err) {
    /*bootstrap gets stuck if if two modals are called in succession, so force
    the removal of shaded background with the following line */
    $('.modal-backdrop').removeAttr('class','in') 

    //add a notification of failed login to login error modal then restart modal
    $('#login_error').attr('class','alert')
                     .text('Login error, please try again.');
    $('#loginButton').click();
};

function logout() {
    logged_in = false;
    $('#loggedInMenu').hide();
    $('#dLabel').text('');

    $('#loginButton').show();
    $('#registration').show();
    $('#Sputnik').click();
    
    //clear user data:
    $('.table').empty()
    SITE_POSITIONS = [];
    OPEN_ORDERS = [];
    AUTHEXTRA = {};
    console.log(OPEN_ORDERS);
    //need to unsubscribe from everything.

    session.close();
}

function getTradeHistory(ticker) {
    var contract_unit = ' ฿';
    var now = new Date();
    var then = new Date(now.getTime());

    then.setDate(now.getDate() - 7);

    session.call(get_trade_history_URI, SITE_TICKER, 7 * 24 * 3600).then(
        function (trades) {
            build_trade_graph(trades);
            TRADE_HISTORY = trades.reverse();
            tradeTable(TRADE_HISTORY, true);
        })
}

function getChatHistory() {
    session.call(get_chat_history_URI).then(
        function(chats) {
            for (chat in chats){
                CHAT_MESSAGES.push(chats[chat]);
            }

            $('#chatArea').html(CHAT_MESSAGES.join('\n'));
            $('#chatArea').scrollTop($('#chatArea')[0].scrollHeight);
        })
}

function placeOrder(order) {
    notifications.processing(order);
    session.call(place_order_URI, order).then(
        function (order_status) {
            notifications.dismiss_processing(order_status)
            if (order_status == false) {
                notifications.orderError();
            }
        }
    );
    
}

function cancelOrder(cancel) {
    session.call(cancel_order_URI, cancel).then(
        function (res) {
            $('#cancel_order_row_' + cancel).addClass('warning');
            $('#cancel_button_' + order_id).attr('disabled', 'disabled')
                .removeClass('btn-danger');
            //todo: this is disgusting, change that.  Agreed.
            //setTimeout(getOpenOrders, 1000);
        })
}

function getPositions() {
    session.call(positions_URI).then(
        function (positions) {

            SITE_POSITIONS = positions;

            var cash_positions = Object()
            var contract_positions = Object()
            var open_tickers = _.pluck(OPEN_ORDERS,'ticker')

            for (var key in positions)
                if(positions[key]['contract_type'] == 'cash')  {
                    cash_positions[key] = positions[key];
                }else{
                if (positions[key]['position'] != 0 || _.contains(open_tickers, positions[key]['ticker']))
                    contract_positions[key] = positions[key];
                }


            displayCash(true, cash_positions);
            displayCash(false, cash_positions);
            displayPositions(true, contract_positions);
            displayPositions(false, contract_positions);
        });
}

function orderBook(ticker) {
    console.log('in orderBook');
    session.call(get_order_book_URI, ticker).then(
        function (book) {
            ORDER_BOOK = book;
            var buyBook = [];
            var sellBook = [];

            var denominator = MARKETS[ticker]['denominator'];
            var tick_size = MARKETS[ticker]['tick_size'];
            var contract_type = MARKETS[ticker]['contract_type'];
            //var dp = decimalPlacesNeeded(denominator * percentage_adjustment / tick_size);

            for (var i = 0; i < book.length; i++) {
                var price = Number(book[i]['price']);
                var quantity = book[i]['quantity'];
                ((book[i]['order_side'] == 0) ? buyBook : sellBook).push([price , quantity]);
            }

            buyBook = stackBook(buyBook);
            sellBook = stackBook(sellBook);

            sellBook.reverse();

            graphTable(buyBook, "buy",true);// ORDER_BOOK_VIEW_SIZE);
            graphTable(sellBook, "sell",true);//ORDER_BOOK_VIEW_SIZE);
            suggestOrder()
        }
    );
}

function withdraw() {
    session.call(withdraw_URI, 'BTC', withdrawAddress.value, Math.round(100000000 * Number(withdrawAmount.value))).then(
        function (res) {
            console.log(res);
        }
    )
}

$('#withdrawButton').click(function(){
    withdraw();
});


function getCurrentAddress() {
    session.call(get_current_address_URI).then(
        function (addr) {
            console.log(addr);
            $('#deposit_address').attr('href', "bitcoin:" + addr).text(addr);
            $('#qrcode').empty();
            new QRCode(document.getElementById("qrcode"), "bitcoin:" + addr);
        }
    )
}

function change_password(old_password, new_password) {
    old_password_hash = ab.deriveKey(old_password,AUTHEXTRA);
    new_password_hash = ab.deriveKey(new_password,AUTHEXTRA);
    console.log(old_password_hash);
    session.call(change_password_URI,old_password_hash, new_password_hash).then(
        function (res) {
            if (res) {
                alert('success!'); 
                $('.modal').modal('hide');
            } else {
                alert('password reset failed');
            }

        }
    )
}

function getNewAddress() {
    session.call(get_new_address_URI).then(
        function (addr) {
            console.log(addr);
        }
    )
}

function registerTwoFactor(confirmation) {
    notifications.processing('confirmation');
    session.call(register_two_factor_URI, confirmation).then(
        function (res) {
            notifications.dismiss_processing(res)
            console.log(res);
            if (res) {
              two_factor.value = 'enabled';
              TWO_FACTOR_ON = true;
              twoFactorSetting();
            }
        }
    )
}

function disableTwoFactor(code) {
    session.call(disable_two_factor_URI, code).then(
        function(res) {
            if(res){
                console.log('disabled');
                two_factor.value = '';
                TWO_FACTOR_ON = false;
                twoFactorSetting();
            }
        })
}
function getNewTwoFactor() {
    session.call(get_new_two_factor_URI).then(
        function(secret) {
            console.log(secret);
            console.log("otpauth://totp/Sputnik:" + login.value +  "?secret=" + secret + "&issuer=SputnikMKT")
            $('#twoFactor').empty();
            new QRCode(document.getElementById("twoFactor"), "otpauth://totp/Sputnik:" + login.value + "?secret=" + secret + "&issuer=SputnikMKT");
        })
}

function getOpenOrders() {
    console.log('Making getOpenOrders RPC call');
    session.call(get_open_orders_URI).then(
        function (orders) {
            console.log('Ended RPC call, drawing');
            OPEN_ORDERS = orders
            displayOrders(true, orders);
            displayOrders(false, orders);
        }
    );
}

function getMarkets() {
    console.log('in getMarkets');
    session.call(markets_URI).then(
        function (res) {
            newMarketsToDisplay(res);
            MARKETS = res;

            //load up the splash page
            welcome (MARKETS);

            //load the active markets for search typeahead.
            $('#search').typeahead({source : _.keys(MARKETS)});

            // randomly select a defualt market
            var keys = [];
            for (key in MARKETS) {
                keys.push(key)
            }
            setSiteTicker(keys[Math.floor((keys.length) * Math.random())]);

            for (key in MARKETS)
                if (MARKETS[key].contract_type == 'futures')
                    session.subscribe(safe_price_URI + '#' + key, onSafePrice);
            console.log(SITE_TICKER);
        });
}

function getSafePrices() {
    session.call(get_safe_prices_URI, []).then(
        function (res) {
            SAFE_PRICES = res;
        }
    );
}

function makeAccount(name, psswd, email, bitmsg) {
    console.log('in make account');
    var salt = Math.random().toString(36).slice(2);
    AUTHEXTRA['salt'] = salt;

    var psswdHsh = ab.deriveKey(psswd, AUTHEXTRA );

    console.log('making session call for makeAccount');
    session.call(make_account_URI, name, psswdHsh, salt,  email, bitmsg).then(
        function (res) {
            login.value = registerLogin.value;
            if (res){
                do_login(registerLogin.value, registerPassword.value);
            } else {
                alert('user name or email taken');
            }
        })
}