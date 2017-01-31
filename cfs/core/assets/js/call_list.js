import {
    Page,
    buildURL,
    cloneFilter,
    toggleFilter
}
    from "./core";
import Ractive from "ractive";
import _ from "underscore-contrib";
import d3 from "d3";
import moment from "moment";

import "../styles/calls.scss";

var apiURL = "/api/" + AGENCY.code + "/calls/";

var Pagination = Ractive.extend({
    template: require("../templates/pagination.html"),
    isolated: true
});

var Call = Ractive.extend({
    template: require("../templates/call.html"),
    data: {
        d: function (val) {
            if (!val) {
                return "None";
            } else {
                return val;
            }
        },
        timeFormat: function (val) {
            if (!val) {
                return "-";
            }
            var m = moment(val);
            return m.format("lll");
        }
    },
    calculated: {
        cancelledText: function () {
            if (this.get('cancelled')) {
                return 'True';
            } else {
                return 'False';
            }
        }
    }
});

var ClickField = Ractive.extend({
    template: require("../templates/click_field.html")
})

var callList = new Page({
    components: {
        Call: Call,
        Pagination: Pagination,
        ClickField: ClickField
    },
    el: document.getElementById("dashboard"),
    template: require("../templates/call_list.html"),
    data: {
        page: 1,
        perPage: 50,
        calls: {},
        config: SITE_CONFIG
    },
    computed: {
        topCount: function () {
            var count = this.get("page") * this.get("perPage");
            return Math.min(this.get("calls.count"), count);
        },
        maxPage: function () {
            return Math.ceil(this.get("calls.count") / this.get("perPage"));
        }
    },
    filterUpdated: function (filter) {
        this.set("page", 1);
        this.reloadCalls(filter, 1);
    },
    reloadCalls: function (filter, page) {
        this.set("loading", true);
        d3.json(
            buildURLWithPage(apiURL, filter, page), _.bind(
                function (error, newCalls) {
                    if (error) throw error;
                    this.set("loading", false);
                    this.set("initialload", false);
                    newCalls = cleanupData(newCalls);
                    this.set("calls", newCalls);
                }, this));
    }
});

callList.observe("page", function (newPage) {
    callList.reloadCalls(callList.get("filter"), newPage);
});

callList.on("Pagination.nextPage", _.bind(function () {
    if (this.get("page") < this.get("maxPage")) {
        this.set("page", this.get("page") + 1);
    }
    return false;
}, callList));

callList.on("Pagination.prevPage", _.bind(function () {
    if (this.get("page") > 1) {
        this.set("page", this.get("page") - 1);
    }
    return false;
}, callList));

callList.on("ClickField.addFilter", _.bind(function (event, field, value) {
    toggleFilter(callList, field, value);
    return false;
}, callList));


function cleanupData(data) {
    return data;
}

function buildURLWithPage(url, filter, page) {
    var params = cloneFilter(callList);
    params.page = page;
    return buildURL(url, params);
}
