# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2016  开阖软件(<http://www.osbzr.com>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp import fields, models, api
from openerp.exceptions import except_orm

BUY_ORDER_STATES = [
        ('draft', '草稿'),
        ('approved', '已审核'),
        ('confirmed', '未入库'),
        ('part_in', '部分入库'),
        ('all_in', '全部入库'),
    ]
BUY_RECEIPT_STATES = [
        ('draft', '草稿'),
        ('approved', '已审核'),
        ('confirmed', '未付款'),
        ('part_paid', '部分付款'),
        ('paid', '全部付款'),
    ]
READONLY_STATES = {
        'approved': [('readonly', True)],
        'confirmed': [('readonly', True)],
    }
class buy_order(models.Model):
    _name = "buy.order"
    _inherit = ['mail.thread']
    _description = u"采购订单"
    _order = 'date desc, id desc'

    @api.one
    @api.depends('line_ids.subtotal', 'discount_rate')
    def _compute_amount(self):
        '''计算订单合计金额，并且当优惠率改变时，改变优惠金额和优惠后金额'''
        self.total = sum(line.subtotal for line in self.line_ids)
        self.discount_amount = self.total * self.discount_rate * 0.01
        self.amount = self.total - self.discount_amount

    partner_id = fields.Many2one('partner', u'供应商', required=True, states=READONLY_STATES)
    date = fields.Date(u'单据日期', states=READONLY_STATES, default=lambda self: fields.Date.context_today(self),
            select=True, help=u"描述了询价单转换成采购订单的日期，默认是订单创建日期。", copy=False)
    planned_date = fields.Date(u'交货日期', states=READONLY_STATES, default=lambda self: fields.Date.context_today(self), select=True, help=u"订单的预计交货日期")
    name = fields.Char(u'单据编号', required=True, select=True, copy=False,
        default='/', help=u"采购订单的唯一编号，当创建时它会自动生成有序编号。")
    type = fields.Selection([('buy','购货'),('return','退货')], u'类型', default='buy')
    line_ids = fields.One2many('buy.order.line', 'order_id', u'采购订单行', states=READONLY_STATES, copy=True)
    notes = fields.Text(u'备注', states=READONLY_STATES)
    discount_rate = fields.Float(u'优惠率(%)', states=READONLY_STATES)
    validator_id = fields.Many2one('res.users', u'审核人', copy=False)
    state = fields.Selection(BUY_ORDER_STATES, u'订单状态', readonly=True, help=u"采购订单的状态", select=True, copy=False, default='draft')
    total = fields.Float(string=u'合计', store=True,
            compute='_compute_amount', track_visibility='always', help=u'所有订单行小计之和')
    discount_amount = fields.Float(string=u'优惠金额', store=True, states=READONLY_STATES,
            compute='_compute_amount', track_visibility='always')
    amount = fields.Float(string=u'优惠后金额', store=True, states=READONLY_STATES,
            compute='_compute_amount', track_visibility='always')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', '采购订单号必须唯一!'),
    ]

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].get('buy.order') or '/'
        new_id = super(buy_order, self).create(vals)
        return new_id

    @api.one
    def buy_approve(self):
        '''审核购货订单'''
        self.write({'state': 'approved', 'validator_id': self._uid})
        return True

    @api.one
    def buy_refuse(self):
        '''反审核购货订单'''
        self.write({'state': 'draft'})
        return True

    @api.one
    def buy_generate_order(self):
        '''由购货订单生成采购入库单'''
        assert(len(self._ids) == 1), 'This option should only be used for a single id at a time'

        res = []
        dict = []
        ret = []

        for line in self.line_ids:
            dict.append({
                'goods_id': line.goods_id and line.goods_id.id or '',
                'spec': line.spec,
                'uom_id': line.uom_id.id,
                'warehouse_id': line.warehouse_id and line.warehouse_id.id or '',
                'warehouse_dest_id': line.warehouse_dest_id and line.warehouse_dest_id.id or '',
                'goods_qty': line.quantity,
                'price': line.price,
                'discount_rate': line.discount_rate,
                'discount': line.discount,
                'amount': line.amount,
                'tax_rate': line.tax_rate,
                'tax_amount': line.tax_amount,
                'subtotal': line.subtotal or 0.0,
                'note': line.note or '',
                'share_cost': 0,
            })

        for i in range(len(dict)):
            ret.append((0, 0, dict[i]))
        receipt_id = self.pool.get('buy.receipt').create(self._cr, self._uid, {
                            'partner_id': self.partner_id.id,
                            'origin': self.name,
                            'line_in_ids': ret,
                            'discount_rate': self.discount_rate,
                            'discount_amount': self.discount_amount,
                            'amount': self.amount,
#                             'total_cost':,
                            'state': 'draft',
                        }, context=self._context)
        res.append(receipt_id)
        view_id = self.env['ir.model.data'].xmlid_to_res_id('buy.buy_receipt_form')
        self.write({'state': 'confirmed'})
        return {
            'name': u'采购入库单',
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': False,
            'views': [(view_id, 'form')],
            'res_model': 'buy.receipt',
            'type': 'ir.actions.act_window',
            'domain':[('id','=',receipt_id)],
            'target': 'current',
        }

class buy_order_line(models.Model):
    _name = 'buy.order.line'
    _description = u'采购订单明细'

    @api.one
    @api.depends('goods_id')
    def _compute_uom_id(self):
        '''当订单行的产品变化时，带出产品上的单位'''
        self.uom_id = self.goods_id.uom_id

    @api.model
    def _default_warehouse(self):
        context = self._context or {}
        if context.get('warehouse_type'):
            return self.pool.get('warehouse').get_warehouse_by_type(self._cr, self._uid, context.get('warehouse_type'))

        return False

    @api.model
    def _default_warehouse_dest(self):
        context = self._context or {}
        if context.get('warehouse_dest_type'):
            return self.pool.get('warehouse').get_warehouse_by_type(self._cr, self._uid, context.get('warehouse_dest_type'))

        return False

    @api.one
    @api.depends('quantity', 'price', 'discount_rate', 'tax_rate')
    def _compute_all_amount(self):
        '''当订单行的数量、购货单价、折扣率、税率改变时，改变折扣额、金额、税额、价税合计'''
        amt = self.quantity * self.price
        discount = amt * self.discount_rate * 0.01
        amount = amt - discount
        tax_amt = amount * self.tax_rate * 0.01
        self.discount = discount
        self.amount = amount
        self.tax_amount = tax_amt
        self.subtotal = amount + tax_amt

    goods_id = fields.Many2one('goods', u'商品')
    spec = fields.Char(u'属性')
    uom_id = fields.Many2one('uom', u'单位', compute=_compute_uom_id)
    warehouse_id = fields.Many2one('warehouse', u'调出仓库', default=_default_warehouse)
    warehouse_dest_id = fields.Many2one('warehouse', u'调入仓库', default=_default_warehouse_dest)
    quantity = fields.Float(u'数量')
    price = fields.Float(u'购货单价')
    discount_rate = fields.Float(u'折扣率%')
    discount = fields.Float(u'折扣额', compute=_compute_all_amount)
    amount = fields.Float(u'金额', compute=_compute_all_amount)
    tax_rate = fields.Float(u'税率(%)')
    tax_amount = fields.Float(u'税额', compute=_compute_all_amount)
    subtotal = fields.Float(u'价税合计', compute=_compute_all_amount)
    note = fields.Char(u'备注')
    origin = fields.Char(u'源单号')
    order_id = fields.Many2one('buy.order', u'订单编号', select=True, required=True, ondelete='cascade')

class buy_receipt(models.Model):
    _name = "buy.receipt"
    _inherits = {'wh.move': 'buy_move_id'}
    _inherit = ['mail.thread']
    _description = u"采购入库单"

    @api.one
    @api.depends('line_in_ids.subtotal', 'discount_rate', 'payment')
    def _compute_all_amount(self):
        '''当优惠率改变时，改变优惠金额和优惠后金额'''
        self.total = sum(line.subtotal for line in self.line_in_ids)
        self.discount_amount = self.total * self.discount_rate * 0.01
        self.amount = self.total - self.discount_amount
        self.debt = self.amount - self.payment

    buy_move_id = fields.Many2one('wh.move', u'入库单', required=True, ondelete='cascade')
    origin = fields.Char(u'源单号')
    discount_rate = fields.Float(u'优惠率(%)', states=READONLY_STATES)
    discount_amount = fields.Float(u'优惠金额', compute=_compute_all_amount, states=READONLY_STATES)
    amount = fields.Float(u'优惠后金额', compute=_compute_all_amount, states=READONLY_STATES)
    payment = fields.Float(u'本次付款', states=READONLY_STATES)
    bank_account_id = fields.Many2one('bank.account', u'结算账户', default='(空)')
    debt = fields.Float(u'本次欠款', compute=_compute_all_amount)
    total_cost = fields.Float(u'采购费用')
    state = fields.Selection(BUY_RECEIPT_STATES, u'付款状态', default='draft', readonly=True, help=u"采购入库单的状态", select=True, copy=False)

    @api.model
    def create(self, vals):
        '''创建采购入库单时判断结算账户和付款额'''
        if vals.get('bank_account_id') and vals.get('payment') == 0:
            raise except_orm(u'警告！', u'结算账户不为空时，需要输入付款额！')
        elif vals.get('payment') != 0 and not vals.get('bank_account_id'):
            raise except_orm(u'警告！', u'付款额不为空时，请选择结算账户！')
        elif vals.get('payment') > vals.get('amount'):
            raise except_orm(u'警告！', u'本次付款金额不能大于折后金额！')
        return super(buy_receipt, self).create(vals)

    @api.multi
    def write(self, vals):
        '''修改采购入库单时判断结算账户和付款额'''
        if vals.get('bank_account_id') and vals.get('payment') == 0:
            raise except_orm(u'警告！', u'结算账户不为空时，需要输入付款额！')
        elif vals.get('payment') != 0 and not vals.get('bank_account_id'):
            raise except_orm(u'警告！', u'付款额不为空时，请选择结算账户！')
        elif vals.get('payment') > vals.get('amount'):
            raise except_orm(u'警告！', u'本次付款金额不能大于折后金额！')
        return super(buy_receipt, self).write(vals)

    @api.one
    def buy_in_approve(self):
        '''审核采购入库单，更新购货订单的状态和本单的付款状态，并生成源单'''
        if self.bank_account_id and self.payment == 0:
            raise except_orm(u'警告！', u'结算账户不为空时，需要输入付款额！')
        elif self.payment != 0 and not self.bank_account_id:
            raise except_orm(u'警告！', u'付款额不为空时，请选择结算账户！')

        order = self.env['buy.order'].search([('name', '=', self.origin)])
        if order.quantity < self.line_in_ids.goods_qty:
            raise except_orm(u'警告！', u'入库数量不能超过购货订单数量！')
        elif order.quantity > self.line_in_ids.goods_qty:
            order.write({'state': 'part_in'})
        else:
            order.write({'state': 'all_in'})

        if self.payment > self.amount:
            raise except_orm(u'警告！', u'本次付款金额不能大于折后金额！')
        elif self.payment == 0:
            self.write({'state': 'confirmed'})
        elif self.payment < self.amount:
            self.write({'state': 'part_paid'})
        else:
            self.write({'state': 'paid'})
        self.write({'approve_uid': self._uid})
        return True

    @api.one
    def buy_in_refuse(self):
        '''反审核采购入库单'''
        self.write({'state': 'draft'})
        return True

class buy_receipt_line(models.Model):
    _inherit = 'wh.move.line'
    _description = u"采购入库明细"

    @api.one
    @api.depends('goods_qty', 'price', 'discount_rate', 'tax_rate')
    def _compute_all_amount(self):
        '''当订单行的数量、购货单价、折扣率、税率改变时，改变折扣额、金额、税额、价税合计'''
        amt = self.goods_qty * self.price
        discount = amt * self.discount_rate * 0.01
        amount = amt - discount
        tax_amt = amount * self.tax_rate * 0.01
        self.discount = discount
        self.amount = amount
        self.tax_amount = tax_amt
        self.subtotal = amount + tax_amt

    spec = fields.Char(u'属性')
    discount_rate = fields.Float(u'折扣率%')
    discount = fields.Float(u'折扣额', compute=_compute_all_amount)
    amount = fields.Float(u'购货金额', compute=_compute_all_amount)
    tax_rate = fields.Float(u'税率(%)')
    tax_amount = fields.Float(u'税额', compute=_compute_all_amount)
    subtotal = fields.Float(u'价税合计', compute=_compute_all_amount)
    share_cost = fields.Float(u'采购费用')
